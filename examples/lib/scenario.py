"""Scenario tests (chapter 10): one task's run over a fixed list of replies from a ScriptedModel.

A scenario shows how the harness handles that one sequence: the refusal, the gate's hold, the stop rule. It says
nothing about how a model behaves; the scores in chapter 10 do that. ``scripted_run`` returns the run and whether it
counts as done under the scoring rule (plan section 6). The caller reads the run's copy, then closes the run, since
closing removes the copy.
"""
from __future__ import annotations

import json
from pathlib import Path

from .case import CASE, load_tasks
from .loop import Run, Stops, run_task
from .models import ScriptedModel
from .tasks import score
from .tools import V1, ToolSet
from .trace import IdCounter


def scripted_run(task_id: str, replies: list[str], tools: ToolSet = V1, *, stops: Stops = Stops(),
                 case: Path = CASE) -> tuple[Run, bool]:
    """Run one task on a fresh copy of ``case`` with the scripted replies. Returns the run and its done flag."""
    task = load_tasks(only=[task_id])[0]
    run = run_task(ScriptedModel(replies), task, tools, max_steps=tools.step_cap, ids=IdCounter(), stops=stops,
                   case=case)
    return run, score(task, run)


class KeptModel(ScriptedModel):
    """A ScriptedModel that keeps each request's messages as text in ``sent``, so a scenario can check what the model
    was sent. The replies are the same as ScriptedModel's."""

    def __init__(self, replies: list) -> None:
        super().__init__(replies)
        self.sent: list[str] = []

    def reply(self, messages: list[dict], tools: list[dict]):
        self.sent.append(json.dumps(messages))
        return super().reply(messages, tools)
