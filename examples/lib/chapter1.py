"""Helpers for chapter 1's examples: the raw text of a tool call, and the printed report of one run.

Added in chapter 1 and used only by its examples. Nothing here changes what the loop, the tools or the models do.
"""
from __future__ import annotations

import json

from .case import DATA, Task
from .loop import Run, run_task
from .models import Model, Reply
from .tasks import score
from .tools import ToolSet
from .trace import IdCounter

SOLUTION = DATA / "solutions" / "T-01" / "unitcraft" / "format.py"


class Recorder:
    """Wraps a model and keeps each reply it gives, so an example can show what the parser made of it."""

    def __init__(self, inner: Model) -> None:
        self.inner = inner
        self.replies: list[Reply] = []

    def reply(self, messages: list[dict], tools: list[dict]) -> Reply:
        reply = self.inner.reply(messages, tools)
        self.replies.append(reply)
        return reply


def call(name: str, **arguments: str) -> str:
    """The raw reply text of one tool call: a JSON object with its name and arguments, in ``<tool_call>`` tags."""
    body = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False)
    return f"<tool_call>\n{body}\n</tool_call>"


def report(model: Model, task: Task, tools: ToolSet) -> tuple[Run, bool]:
    """Run one task, print one line per step and the counts, and return the run with whether it counts as done."""
    run = run_task(model, task, tools, max_steps=tools.step_cap, ids=IdCounter())
    try:
        for line in run.trace.lines():
            print(line)
        done = score(task, run)
        print(f"steps: {run.steps}")
        print(f"tool calls: {run.tool_calls}")
        print(f"ended: {run.ended}")
        return run, done
    finally:
        run.close()
