"""Subagents: a child loop with its own step budget, tools and transcript, and the handoff its parent receives.

The child runs the same loop as the parent (``run_task``) on a scratch copy of its own. Its budget counts its own model
calls. Its transcript is the message list its loop built, and that stays with the child. The parent gets a ``Handoff``
and nothing else: the child's ID, how it ended, its counts, the files it read and changed, and either its summary or,
when a stop ended it, the stop reason and a question.

A stop becomes a handoff to a person. ``handoff_for`` builds the stop reason, the counts and the question from the
run's own record (its trace, its streak and its test counts). No model writes any of it, so a replayed run gives the
same handoff every time. The parent is a loop of its own (``hand_to_parent``), and it puts the question to the person
with ``ask_user``. The wording is this module's, not a vendor's.

Counts are steps, calls and characters. Tokens are estimated with chapter 5's rule (``CHARS_PER_TOKEN``).
"""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from .case import CASE, Task, load_tasks
from .context import CHARS_PER_TOKEN
from .loop import EDITS, Run, Stops, run_task
from .models import Model, Reply, ReplayModel, make_reply
from .tasks import score
from .tools import S_ASK_USER, S_FINISH, V1, Tool, ToolResult, ToolSet, Workspace
from .trace import IdCounter, result_class

STUCK = ("step_cap", "repeated_call", "no_progress")  # the stops that hand a run back to a person
PARENT_SYSTEM = (
    "A child agent stopped on a subtask. Its handoff gives how it ended, what it tried as counts, and a question. "
    "Put the question to the person with ask_user. Reply with a tool call only."
)
PARENT = ToolSet("parent", PARENT_SYSTEM, 2, (S_ASK_USER, S_FINISH))


@dataclass(frozen=True)
class Handoff:
    """What the parent receives from a child: fields only, never the child's transcript.

    ``tried`` counts the steps that made each tool call, sorted by tool name. ``files_changed`` lists only the files
    whose bytes differ from the case at the end of the run; a file an edit named but did not change is left out.
    ``edits_failed`` counts the edit calls that did not apply. ``stop`` and ``question`` are set when a stop ended the
    child; ``summary`` when it finished. ``question`` is the child's own when it asked one.
    """

    child: str
    ended: str
    steps: int
    budget: int
    tried: tuple[tuple[str, int], ...]
    files_read: tuple[str, ...]
    files_changed: tuple[str, ...]
    edits_failed: int = 0
    stop: str = ""
    question: str = ""
    summary: str = ""

    @property
    def files_edited(self) -> tuple[str, ...]:
        """The old name of ``files_changed``, kept for callers that still use it."""
        return self.files_changed

    @property
    def stuck(self) -> bool:
        return self.ended in STUCK

    @property
    def text(self) -> str:
        """The handoff as the parent reads it: one labelled line per field that is set."""
        lines = [
            f"child: {self.child}",
            f"ended: {self.ended}",
            f"steps: {self.steps} of {self.budget}",
            "tried: " + (", ".join(f"{tool} {n}" for tool, n in self.tried) or "nothing"),
            "files read: " + (", ".join(self.files_read) or "none"),
            "files changed: " + (", ".join(self.files_changed) or "none"),
            f"edits failed: {self.edits_failed}",
        ]
        if self.stop:
            lines.append(f"stop: {self.stop}")
        if self.summary:
            lines.append(f"summary: {self.summary}")
        if self.question:
            lines.append(f"question: {self.question}")
        return "\n".join(lines)


@dataclass
class Child:
    """A finished child. The handoff goes to the parent; the rest is the child's own record.

    ``run`` keeps the child's scratch copy open, so scoring can read it. Call ``run.close()`` when done.
    """

    handoff: Handoff
    transcript: list[dict]
    trace: tuple[str, ...]
    tool_names: tuple[str, ...]
    run: Run


class _Recorder:
    """Wraps the child's model. It keeps the loop's own message list, which is complete when the run ends, and the
    first call of each reply, the one the loop runs."""

    def __init__(self, inner: Model) -> None:
        self.inner = inner
        self.messages: list[dict] = []
        self.first_calls: list[dict] = []

    def reply(self, messages: list[dict], tools: list[dict]) -> Reply:
        self.messages = messages
        reply = self.inner.reply(messages, tools)
        self.first_calls.append(reply.tool_calls[0] if reply.tool_calls else {})
        return reply


def _paths(calls: list[dict], names: tuple[str, ...]) -> tuple[str, ...]:
    """The sorted, distinct paths the calls to these tools named."""
    return tuple(sorted({str(c["arguments"]["path"]) for c in calls
                         if c.get("name") in names and "path" in c["arguments"]}))


def _bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _changed(run: Run, paths: tuple[str, ...]) -> tuple[str, ...]:
    """The paths whose bytes differ between the run's scratch copy and the case. An edit that failed, or wrote the
    same bytes back, is not a change."""
    return tuple(p for p in paths if _bytes(run.scratch / p) != _bytes(run.case / p))


def _handoff(child: str, run: Run, budget: int, stops: Stops, calls: list[dict]) -> Handoff:
    """Build what the parent receives from a finished run. Stuck runs get a stop reason and a question."""
    tried = Counter(r["tool"] for r in run.trace.records if r["tool"] != "-")
    named = _paths(calls, EDITS)  # the paths the edit calls named, applied or not; the question below uses them
    failed = sum(1 for r in run.trace.records if r["tool"] in EDITS and result_class(r["brief"]) != "ok")
    stop = question = summary = ""
    if run.ended == "repeated_call":
        n = run.steps - run.streak_from + 1
        stop = (f"repeated_call ({run.stuck_on}, same arguments {n} times in a row, "
                f"steps {run.streak_from} to {run.steps})")
        question = (f"The agent sent the same {run.stuck_on} call {n} times in a row. "
                    "Should a person make this change, or should the agent try another approach?")
    elif run.ended == "no_progress":
        k = stops.no_progress_limit
        stop = f"no_progress ({run.stuck_on}, {k} edits in a row left the test result unchanged: {run.counts})"
        question = (f"The last {k} edits left the test result unchanged (last result: {run.counts}). Should a person "
                    f"look at {', '.join(named)}, or should the agent keep going?")
    elif run.ended == "step_cap":
        stop = f"step_cap (no finish within {budget} steps)"
        question = (f"The agent used all {budget} steps without finishing. Should a person take this task from "
                    "here, or should it get more steps?")
    else:
        question, summary = run.question, run.summary
    return Handoff(child=child, ended=run.ended, steps=run.steps, budget=budget, tried=tuple(sorted(tried.items())),
                   files_read=_paths(calls, ("read_file",)), files_changed=_changed(run, named), edits_failed=failed,
                   stop=stop, question=question, summary=summary)


def run_child(model: Model, task: Task, tools: ToolSet, *, budget: int, ids: IdCounter,
              stops: Stops = Stops(), case: Path = CASE) -> Child:
    """Run a child on its own scratch copy, with ``budget`` steps of its own. Its ID comes from ``ids`` under the kind
    ``child``, so child IDs never use up run IDs."""
    child = ids.next("child")
    recorder = _Recorder(model)
    run = run_task(recorder, task, tools, max_steps=budget, ids=ids, case=case, stops=stops)
    return Child(handoff=_handoff(child, run, budget, stops, recorder.first_calls), transcript=recorder.messages,
                 trace=tuple(run.trace.lines()), tool_names=tuple(t.name for t in tools.tools), run=run)


def hand_to_parent(model: Model, handoff: Handoff, ids: IdCounter) -> Run:
    """Run the parent with the handoff's text as its issue. The scratch copy is removed; the run's fields stay."""
    task = Task(id=handoff.child, kind="stop", issue=handoff.text, check="", unchanged=())
    run = run_task(model, task, PARENT, max_steps=PARENT.step_cap, ids=ids)
    run.close()
    return run


def asks(question: str) -> Reply:
    """A parent's reply that puts the question to the person with ``ask_user``."""
    return make_reply("<tool_call>" + json.dumps({"name": "ask_user", "arguments": {"question": question}}) +
                      "</tool_call>")


def characters(messages: list[dict]) -> int:
    """The characters in the messages' text. Tool schemas are left out, so this counts what the child read."""
    return sum(len(m["content"]) for m in messages)


def tokens(chars: int) -> int:
    """The estimated tokens for a number of characters, with chapter 5's rule, rounded up."""
    return math.ceil(chars / CHARS_PER_TOKEN)


def task_set_children(stops: Stops) -> list[tuple[Task, Handoff, bool, list[dict]]]:
    """Every task in file order, replayed as a child on the task-set recording with the task set's step cap. The
    children share one ID counter, so their run IDs match the recording's. Each row holds the task, the handoff, whether
    the scoring rule counts the task done, and the child's transcript."""
    ids, rows = IdCounter(), []
    for task in load_tasks():
        child = run_child(ReplayModel("task-set", task.id), task, V1, budget=V1.step_cap, ids=ids, stops=stops)
        rows.append((task, child.handoff, score(task, child.run), child.transcript))
        child.run.close()
    return rows


START_CHILD = "start_child"
PARENT_STARTS_SYSTEM = ("You are the parent. Start the child with start_child. Its handoff gives how it ended and a "
                        "question. Put that question to the person with ask_user. Reply with one tool call per reply.")


class StartArgs(BaseModel):
    task_id: str


def start_child_tools(task: Task, child_model: Callable[[], Model], *, ids: IdCounter, stops: Stops,
                      children: list[Child], budget: int = V1.step_cap, step_cap: int = 4) -> ToolSet:
    """A parent's tools: ``start_child`` runs a child on ``task`` with its own budget and returns the child's handoff as
    the tool's text, and ``ask_user``. Each start calls ``child_model()`` for a fresh model and appends the child to
    ``children``, which keeps the child's own record."""

    def start(ws: Workspace, args: StartArgs) -> ToolResult:
        if args.task_id != task.id:
            return ToolResult(f"error: no task {args.task_id} in this set", brief="error: unknown task")
        child = run_child(child_model(), task, V1, budget=budget, ids=ids, stops=stops)
        children.append(child)
        child.run.close()
        return ToolResult(child.handoff.text, brief=f"child {child.handoff.ended} at step {child.handoff.steps}")

    tool = Tool(START_CHILD, "Start a child on a task of the case, with its own step budget, and return its handoff: "
                "how it ended, its counts, its files and its stop or summary.", StartArgs, start)
    return ToolSet("parent-starts-child", PARENT_STARTS_SYSTEM, step_cap, (tool, S_ASK_USER))


class ParentReadsHandoff:
    """A scripted parent for ``start_child_tools``. It starts the child on its first reply; on its second it asks the
    question that the child's handoff gives. It keeps the messages its loop built."""

    def __init__(self, task_id: str) -> None:
        call = {"name": START_CHILD, "arguments": {"task_id": task_id}}
        self.start_call = "<tool_call>" + json.dumps(call) + "</tool_call>"
        self.calls = 0
        self.messages: list[dict] = []

    def reply(self, messages: list[dict], tools: list[dict]) -> Reply:
        self.calls += 1
        self.messages = messages
        if self.calls == 1:
            return make_reply(self.start_call)
        handed = [m["content"] for m in messages if m["role"] == "tool"][-1]  # the handoff the start call returned
        line = next(x for x in handed.splitlines() if x.startswith("question: "))
        return asks(line[len("question: "):])  # the text after the label
