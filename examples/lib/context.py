"""The context budget, the estimate that checks it, the local compaction, and the notes the agent keeps.

The window is the recorded model's ``n_ctx`` (8192, stored in each recording's manifest), not a hosted API's default.
A reply may take up to ``REPLY`` tokens, so a prompt has ``PROMPT_BUDGET`` tokens. The harness cannot count tokens
exactly without loading the model, so it estimates: one token per ``CHARS_PER_TOKEN`` characters of the messages and
the tool schemas. An example compares that estimate with the counts the recording stored.

Compaction is local and deterministic: the older steps become one summary message, which lists each step's call and
the first line of its result. The last step (its call and its result) is kept word for word, and a cut never falls
on a tool result, since that would leave its call behind. The notes are a file the agent writes with ``note``; they
are sent at every step, after the issue, so a compaction never removes them.

Teaching code: the summary is written by this module, not by the model, so a run replays exactly. Its rules are the
book's, not a vendor's.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .models import Reply, parse_tool_calls
from .tools import S_ASK_USER, S_EDIT_FILE, S_FINISH, S_LIST_FILES, S_READ_FILE, S_RUN_TESTS, S_WRITE_FILE
from .tools import Tool, ToolResult, ToolSet, Workspace

WINDOW = 8192  # the recorded model's n_ctx: recordings/local_model.py, and the task-set manifest's "n_ctx"
REPLY = 1024  # the recorded max_tokens: room the reply may take
PROMPT_BUDGET = WINDOW - REPLY  # 7168 tokens for everything the model reads
CHARS_PER_TOKEN = 3  # the estimate's rule: one token per three characters (estimate_vs_recorded checks it)
SUMMARY_CHARS = 60  # the most of a step's call arguments, and of its result's first line, that the summary keeps

DESC_NOTE = "Add one line to your notes. The notes are shown to you at every step, and they stay when older steps are cut."
PARAM_NOTE = "One fact to keep for later steps, in one line."
SYSTEM_NOTES = (
    "You are a maintenance agent for the unitcraft library. You have eight tools, and you call one per reply:\n"
    "list_files() lists the files in your copy.\n"
    "read_file(path) returns the text of one file.\n"
    "run_tests() runs the visible test suite on your copy and returns the counts.\n"
    "write_file(path, text) creates a new file in your copy; it is refused when the file exists.\n"
    "edit_file(path, old, new) replaces the one occurrence of old with new in an existing file.\n"
    "note(text) adds one line to your notes; the notes are shown to you at every step.\n"
    "ask_user(question) ends the run to ask the person a question, with the reason you need the answer.\n"
    "finish(summary) ends the run with a summary of what you changed and why.\n"
    "When the change is done, call finish with a summary. If a step needs a person's approval, or the task is "
    "ambiguous, out of scope or impossible, call ask_user. Reply with a tool call only."
)


def characters(messages: list[dict], tools: list[dict]) -> int:
    """The characters the estimate counts: every message's text, and the tool schemas as JSON."""
    return sum(len(m["content"]) for m in messages) + len(json.dumps(tools, sort_keys=True))


def estimate(messages: list[dict], tools: list[dict], chars_per_token: int = CHARS_PER_TOKEN) -> int:
    """The estimated prompt tokens: the characters divided by ``chars_per_token``, rounded up."""
    return math.ceil(characters(messages, tools) / chars_per_token)


class Notes:
    """The notes the agent keeps. Each one is a line; with a path, the file is rewritten after every note."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.lines: list[str] = []

    def add(self, text: str) -> int:
        """Keep one note on one line, and return how many notes there are now."""
        self.lines.append(" ".join(text.split()))
        if self.path is not None:
            self.path.write_text("".join(f"- {line}\n" for line in self.lines), encoding="utf-8")
        return len(self.lines)

    def block(self) -> str:
        """The notes as one message's text: the sentence the model reads, then one line per note."""
        return "Your notes so far:\n" + "\n".join(f"- {line}" for line in self.lines)


class NoteArgs(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    text: str = Field(description=PARAM_NOTE)


def note_tool(notes: Notes) -> Tool:
    """The ``note`` tool, bound to one run's notes."""

    def run(ws: Workspace, args: NoteArgs) -> ToolResult:
        count = notes.add(args.text)
        return ToolResult(f"noted: {count} in all", brief=f"note {count}")

    return Tool("note", DESC_NOTE, NoteArgs, run)


def notes_toolset(notes: Notes) -> ToolSet:
    """Chapter 5's tool set: the v2 tools, strict and with nearest-line edit errors, plus ``note``."""
    return ToolSet("v2+notes", SYSTEM_NOTES, 16,
                   (S_LIST_FILES, S_READ_FILE, S_RUN_TESTS, S_WRITE_FILE, S_EDIT_FILE, S_ASK_USER, S_FINISH,
                    note_tool(notes)), typed_errors=True)


def clean_cut(messages: list[dict], cut: int) -> bool:
    """A cut before ``messages[cut]`` is clean unless that message is a tool result, whose call would be left behind."""
    return messages[cut]["role"] != "tool"


def _first_line(text: str) -> str:
    head = text.strip().splitlines()[0] if text.strip() else ""
    return head[:SUMMARY_CHARS]


def summarise(cut_steps: list[tuple[dict, dict | None]]) -> str:
    """One line per older step: its call, with the arguments cut short, and the first line of its result."""
    lines = []
    for number, (call, result) in enumerate(cut_steps, start=1):
        calls, _ = parse_tool_calls(call["content"])
        if calls:
            args = json.dumps(calls[0]["arguments"], sort_keys=True)[:SUMMARY_CHARS]
            what = f"{calls[0]['name']}({args})"
        else:
            what = "no tool call"
        brief = _first_line(result["content"]) if result is not None else ""
        lines.append(f"step {number}: {what} -> {brief}")
    return "\n".join(lines)


def compact(messages: list[dict]) -> list[dict]:
    """The messages with the older steps replaced by one summary. The last step is kept as it was.

    The system prompt and the issue stay; the summary follows them. Nothing is cut when there is only one step.
    """
    steps = [i for i, m in enumerate(messages) if m["role"] == "assistant"]
    if not steps or steps[-1] <= 2:
        return list(messages)
    last = steps[-1]
    assert clean_cut(messages, last), "the cut must not fall on a tool result"
    older = [i for i in steps if 2 <= i < last]
    cut_steps = [(messages[i], messages[i + 1] if messages[i + 1]["role"] == "tool" else None) for i in older]
    summary = {"role": "user", "content": "Earlier steps, summarised by the harness:\n" + summarise(cut_steps)}
    return messages[:2] + [summary] + messages[last:]


def with_notes(messages: list[dict], notes: Notes) -> list[dict]:
    """The messages with the notes after the issue, when there are any."""
    if not notes.lines:
        return list(messages)
    return messages[:2] + [{"role": "user", "content": notes.block()}] + messages[2:]


@dataclass
class Context:
    """The hook the loop calls before each model call. It returns the messages to send; the loop keeps its own list.

    ``compactions`` counts the calls that were compacted; ``over_budget`` counts the calls still over the budget
    after compaction (the summary cannot cut the system prompt, the issue or the last step).
    """

    notes: Notes = field(default_factory=Notes)
    prompt_budget: int = PROMPT_BUDGET
    chars_per_token: int = CHARS_PER_TOKEN
    compactions: int = 0
    over_budget: int = 0

    def __call__(self, messages: list[dict], tools: list[dict]) -> list[dict]:
        if estimate(with_notes(messages, self.notes), tools, self.chars_per_token) > self.prompt_budget:
            self.compactions += 1
            messages = compact(messages)
        sent = with_notes(messages, self.notes)
        if estimate(sent, tools, self.chars_per_token) > self.prompt_budget:
            self.over_budget += 1
        return sent


class Measured:
    """A model wrapper that keeps each call's messages, tool schemas and the prompt count the model reported."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.requests: list[tuple[list[dict], list[dict], int]] = []

    def reply(self, messages: list[dict], tools: list[dict]) -> Reply:
        reply = self.inner.reply(messages, tools)
        self.requests.append((list(messages), tools, reply.prompt_tokens))
        return reply


class Compacting:
    """Applies a ``Context`` before each call: the wrapped model is sent what the context returns.

    The loop keeps its own messages, so this is the hook's behaviour without a change to ``run_task``: each request
    is the one a ``context=`` argument would send, and a recording made through it replays through it.
    """

    def __init__(self, inner, context: Context) -> None:
        self.inner = inner
        self.context = context

    def reply(self, messages: list[dict], tools: list[dict]) -> Reply:
        return self.inner.reply(self.context(messages, tools), tools)
