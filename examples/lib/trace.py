"""The transcript of a run: one record per step, and the injected counter that numbers runs.

The transcript holds counts and short results, never times, so the printed lines are the same on every machine.
Chapter 11 adds JSON lines and token counts to this module; the step lines printed here do not change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .loop import Run


@dataclass
class Trace:
    """The steps of one run. ``add`` keeps the step's tool and a one-line result."""

    records: list[dict] = field(default_factory=list)

    def add(self, step: int, tool: str, brief: str) -> None:
        line = " ".join(brief.split())[:100]  # one line, capped
        self.records.append({"step": step, "tool": tool, "brief": line})

    def lines(self) -> list[str]:
        """The printed form: ``step 3: run_tests: 1 failed, 4 passed``."""
        return [f"step {r['step']}: {r['tool']}: {r['brief']}" for r in self.records]


class IdCounter:
    """Numbers IDs from 1 per kind: ``run-0001``, ``run-0002``. Injected, so no clock or randomness is used."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def next(self, kind: str) -> str:
        self._counts[kind] = self._counts.get(kind, 0) + 1
        return f"{kind}-{self._counts[kind]:04d}"


# Chapter 11: the JSON-lines record of a run. The counts are the recorded ones; nothing here tokenizes.
# A brief that contains one of these was refused: the harness did not run the call, or a gate or a tool's own path
# check held it. Any other brief starting "error" is a tool that ran and reported an error.
REFUSED = ("not run", "cut off", "malformed", "unknown tool", "invalid arguments", "not a tool this harness runs",
           "not applied", "is not writable", "is not changed by the harness")
# The book's own field names, next to the OpenTelemetry GenAI names they would map to. Data only: the book uses no OTel.
OTEL_TOKEN_FIELDS = {"prompt_tokens": "gen_ai.usage.input_tokens", "completion_tokens": "gen_ai.usage.output_tokens"}


def result_class(brief: str) -> str:
    """``ok``, ``refused`` or ``error``, read from a step's one-line brief (see ``REFUSED``)."""
    if any(mark in brief for mark in REFUSED):
        return "refused"
    return "error" if brief.startswith("error") else "ok"


def dumps(record: dict) -> str:
    """One record as one JSON line: sorted keys, no spaces, ASCII only."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def read_lines(text: str) -> tuple[list[dict], int]:
    """Parse a JSON-lines text into its records, and count the empty pieces skipped. The writer writes no blank line,
    so the only empty piece in a file that ends with a line feed is the one after the last line feed."""
    records, skipped = [], 0
    for piece in text.split("\n"):
        if piece == "":
            skipped += 1
            continue
        records.append(json.loads(piece))
    return records, skipped


class StepRecorder:
    """Wraps a model and passes each request and reply through unchanged. It keeps each step's reply, the tool names
    offered, and where the gate's log stood, so the gate's lines can be read back per step."""

    def __init__(self, inner: Any, gate: Any = None) -> None:
        self.inner, self.gate, self.steps = inner, gate, []

    def reply(self, messages: list[dict], tools: list[dict]) -> Any:
        start = len(self.gate.log) if self.gate is not None else 0
        reply = self.inner.reply(messages, tools)
        self.steps.append({"offered": sorted(t["function"]["name"] for t in tools), "reply": reply, "from": start})
        return reply


def step_records(run: Run, recorder: StepRecorder, parent: str | None = None) -> list[dict]:
    """One record per step, in step order: the calls and their IDs (numbered as the loop numbers them), the first
    call's arguments, its result class, the recorded token counts, the gate's lines for that step, and the names
    offered. The last record carries the stop. ``parent`` is the call ID that started this run, when it is a child."""
    gate = recorder.gate
    ends = [s["from"] for s in recorder.steps[1:]] + [len(gate.log) if gate is not None else 0]
    rows = run.trace.records
    assert len(rows) == len(recorder.steps) == run.steps, "the trace and the replies disagree on the step count"
    records, calls = [], 0
    for index, (step, end, row) in enumerate(zip(recorder.steps, ends, rows), start=1):
        reply = step["reply"]
        if reply.finish_reason == "length" and not reply.tool_calls:
            requests = 1  # the loop counts a cut-off reply as one refused call
        else:
            requests = len(reply.tool_calls) + len(reply.malformed)
        ids = [f"{run.id}-c{calls + k}" for k in range(1, requests + 1)]
        calls += requests
        call = reply.tool_calls[0] if reply.tool_calls else {}
        records.append({
            "run": run.id, "step": index, "calls": ids, "tool": row["tool"], "arguments": call.get("arguments"),
            "malformed": list(reply.malformed), "result": result_class(row["brief"]), "brief": row["brief"],
            "prompt_tokens": reply.prompt_tokens, "completion_tokens": reply.completion_tokens,
            "gate": gate.log[step["from"]:end] if gate is not None else [], "offered": step["offered"],
            "parent": parent, "stop": run.ended if index == len(rows) else "",
        })
    assert calls == run.tool_calls, "the records count a different number of calls than the run"
    return records


def nest(records: list[dict], children: dict[str, list[dict]]) -> list[dict]:
    """The parent's records, with each child's records placed right after the step whose call started it. ``children``
    is keyed by that call's ID, so a child's records sit under its parent ID."""
    out = []
    for record in records:
        out.append(record)
        for call_id in record["calls"]:
            out.extend(children.get(call_id, []))
    return out


def child_under_parent(task: Any, replies: list[str], child_model: StepRecorder, gate: Any, library: Any,
                       child_ids: Any) -> tuple[Run, Any, list[dict]]:
    """A scripted parent that starts ``task`` as a child with ``start_child``. The child runs the gated tools on
    ``library`` with ``child_model``. Returns the parent's run, the child, and the records: the parent's, with the
    child's placed under the call that started it. The imports are inside the function, because ``subagents`` imports
    ``loop``, which imports this module."""
    from .loop import run_task
    from .models import ScriptedModel
    from .permissions import gated
    from .subagents import PARENT_STARTS_SYSTEM, START_CHILD, StartArgs, run_child
    from .tools import S_ASK_USER, V1, Tool, ToolResult, ToolSet

    children = []

    def start(ws: Any, args: StartArgs) -> ToolResult:
        child = run_child(child_model, task, gated(V1, gate), budget=V1.step_cap, ids=child_ids, case=library)
        children.append(child)
        child.run.close()
        return ToolResult(child.handoff.text, brief=f"child {child.handoff.ended} at step {child.handoff.steps}")

    tool = Tool(START_CHILD, "Start a child on a task of the case and return its handoff.", StartArgs, start)
    tools = ToolSet("parent-starts-child", PARENT_STARTS_SYSTEM, 4, (tool, S_ASK_USER))
    parent_model = StepRecorder(ScriptedModel(replies))
    parent = run_task(parent_model, task, tools, max_steps=tools.step_cap, ids=IdCounter())
    parent_records = step_records(parent, parent_model)
    start_id = parent_records[0]["calls"][0]
    child_records = step_records(children[0].run, child_model, parent=start_id)
    return parent, children[0], nest(parent_records, {start_id: child_records})
