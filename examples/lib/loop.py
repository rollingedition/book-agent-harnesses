"""The step loop: send the messages, run the one tool call in the reply, hand the result back, repeat.

A step is one model call. The loop ends when a tool ends the run (``finish`` or ``ask_user``), when the step
budget is spent (``step_cap``), or when the model gives no tool call twice in a row (``no_tool_call``). A reply
with no call gets one retry: the model is told so, and the loop goes on. A reply with several calls runs only
the first; the others are answered with an error, so every request in the transcript has an answer.

Two optional rules (``Stops``) end a run as ``repeated_call`` or ``no_progress``. Both are off by default, and
neither adds anything to the messages, so a run without them makes the same requests as before.

Counts: ``steps`` counts model calls; ``tool_calls`` counts requests, including malformed ones.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .case import CASE, Task, scratch_copy
from .models import Model
from .tools import ToolResult, ToolSet, Workspace
from .trace import IdCounter, Trace

NO_CALL = "error: the reply had no tool call; reply with one tool call"
NOT_RUN = "error: only one tool call runs per reply; this call was not run"
CUT_OFF = "error: your reply was cut off at the token limit; make a smaller change"
EDITS = ("edit_file", "write_file")  # the calls that change the copy; the no-progress rule watches these


@dataclass(frozen=True)
class Stops:
    """Stop rules beyond the step cap and ``finish``/``ask_user``. Every default is off, so a run without them is unchanged.

    ``repeat_limit``: end the run as ``repeated_call`` when this many identical calls come in a row (0 is off).
    ``no_progress_limit``: end the run as ``no_progress`` when this many edits in a row leave the test counts
    where they were (0 is off). The counts come from ``run_tests`` on the copy, which the model does not see.
    """

    repeat_limit: int = 0
    no_progress_limit: int = 0


@dataclass
class Run:
    """What one task's run left behind: its counts, how it ended, and the scratch copy it worked on."""

    id: str
    task_id: str
    case: Path
    scratch: Path
    steps: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    ended: str = ""
    stuck_on: str = ""  # the tool a stop rule ended the run on, when one did
    streak_from: int = 0  # the step where the run of identical calls that ended it began
    counts: str = ""  # the test counts when a no-progress stop ended the run
    question: str = ""
    summary: str = ""
    trace: Trace = field(default_factory=Trace)

    def close(self) -> None:
        """Remove the scratch copy. Call it after scoring."""
        shutil.rmtree(self.scratch, ignore_errors=True)


def run_task(model: Model, task: Task, tools: ToolSet, *, max_steps: int, ids: IdCounter,
             case: Path = CASE, stops: Stops = Stops()) -> Run:
    """Run one task on a fresh scratch copy of the case and return the run. The caller must call ``close``."""
    run = Run(id=ids.next("run"), task_id=task.id, case=case, scratch=scratch_copy(case))
    try:
        _loop(model, task, tools, run, max_steps, stops)
    except BaseException:
        run.close()
        raise
    return run


def _loop(model: Model, task: Task, tools: ToolSet, run: Run, max_steps: int, stops: Stops) -> None:
    ws = Workspace(run.scratch)
    messages = [{"role": "system", "content": tools.system}, {"role": "user", "content": task.issue}]
    no_call = 0
    last_key, streak = None, 0  # the last run call's name and arguments, and how many times in a row it came
    counts = ws.run_tests().splitlines()[0] if stops.no_progress_limit else ""
    flat = 0  # edits in a row that left the counts where they were
    for step in range(1, max_steps + 1):
        reply = model.reply(messages, tools.schemas())
        run.steps = step
        run.prompt_tokens += reply.prompt_tokens
        run.completion_tokens += reply.completion_tokens
        messages.append({"role": "assistant", "content": reply.text})

        if reply.finish_reason == "length" and not reply.tool_calls:
            # The reply hit the token limit before a call that parses: the call is counted and refused, not run.
            run.tool_calls += 1
            run.trace.add(step, "malformed", CUT_OFF)
            messages.append({"role": "tool", "tool_call_id": f"{run.id}-c{run.tool_calls}", "content": CUT_OFF})
            no_call = 0
            continue

        requests = [("call", c) for c in reply.tool_calls] + [("malformed", m) for m in reply.malformed]
        if not requests:
            no_call += 1
            run.trace.add(step, "-", NO_CALL)
            messages.append({"role": "user", "content": NO_CALL})
            if no_call >= 2:
                run.ended = "no_tool_call"
                return
            continue
        no_call = 0

        for index, (kind, item) in enumerate(requests):
            run.tool_calls += 1
            call_id = f"{run.id}-c{run.tool_calls}"
            if index > 0:
                result = ToolResult(NOT_RUN, brief="not run")
                name = "-"
            elif kind == "malformed":
                result = ToolResult(f"error: malformed tool call: {item}", brief="error: malformed call")
                name = "malformed"
            else:
                name = item["name"]
                result = tools.call(ws, name, item["arguments"])
            if index == 0:
                run.trace.add(step, name, result.brief or result.text)
                key = None if kind == "malformed" else (name, json.dumps(item["arguments"], sort_keys=True))
                if key is not None and key == last_key:
                    streak += 1
                else:
                    streak, streak_from = int(key is not None), step
                last_key = key
            messages.append({"role": "tool", "tool_call_id": call_id, "content": result.text})
            if index == 0 and result.end:
                run.ended = result.end
                run.question, run.summary = result.question, result.summary
                return
            if index == 0 and stops.repeat_limit and streak >= stops.repeat_limit:
                run.ended, run.stuck_on, run.streak_from = "repeated_call", name, streak_from
                return
            if index == 0 and stops.no_progress_limit and name in EDITS:
                now = ws.run_tests().splitlines()[0]
                flat = flat + 1 if now == counts else 0
                counts = now
                if flat >= stops.no_progress_limit:
                    run.ended, run.stuck_on, run.counts = "no_progress", name, now
                    return
    run.ended = "step_cap"
