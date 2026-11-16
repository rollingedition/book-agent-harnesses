"""A fixed pipeline (chapter 12): the steps for a task are written down before the run, and no model chooses them.

A pipeline runs the v1 tools in a fixed order on a fresh copy of the case: read each file it will change, make one
exact replacement in each, run the visible tests, and finish. It stops at the first step that fails (an edit whose
old text is not found, or a visible test that fails only after the edit) and never tries another step. Each call
goes through ``V1.call``, so the tools behave as they do for the agent, and the run is scored by ``score`` (plan
section 6), the same as an agent's run.

The edits are written by a person, who knows the answer. The comparison in chapter 12 is therefore about what the
design costs in steps and model calls, not about what a pipeline can find on its own.

Counts: ``run.tool_calls`` is the pipeline's steps (every tool call, ``finish`` included); ``run.steps`` stays 0,
because no model is called.
"""
from __future__ import annotations

from dataclasses import dataclass

from .case import CASE, Task, load_tasks, scratch_copy
from .loop import Run, run_task
from .models import ReplayModel
from .permissions import replay_ids
from .tools import V1, ToolResult, Workspace

FT_LINE = '        Unit("ft", "length", Decimal("0.3048")),\n'
INCH_LINE = '        Unit("in", "length", Decimal("0.0254")),\n'
YARD_LINE = '        Unit("yd", "length", Decimal("0.9144")),\n'


@dataclass(frozen=True)
class Edit:
    """One exact replacement in one file: ``old`` must occur once, or the pipeline stops."""

    path: str
    old: str
    new: str


@dataclass(frozen=True)
class Pipeline:
    """The edits for one task, in order, and the summary the finish step gives."""

    edits: tuple[Edit, ...]
    summary: str


PIPELINES: dict[str, Pipeline] = {
    "T-02": Pipeline((Edit("unitcraft/format.py", 'body = f"{-rounded:.{places}f}"',
                           'body = f"{-rounded:,.{places}f}"'),),
                     "Negative amounts keep their thousands separator."),
    "T-04": Pipeline((Edit("unitcraft/units.py", FT_LINE, FT_LINE + INCH_LINE),), "Added the inch to the unit table."),
    "T-05": Pipeline((Edit("unitcraft/units.py", FT_LINE, FT_LINE + YARD_LINE),), "Added the yard to the unit table."),
}


def _call(run: Run, ws: Workspace, name: str, arguments: dict) -> ToolResult:
    """Run one v1 tool call and count it as one pipeline step."""
    run.tool_calls += 1
    return V1.call(ws, name, arguments)


def failing(text: str) -> list[str]:
    """The test ids of a summary's FAILED lines, in order. The message after " - " is left out: an edit can change
    a failing test's message without changing which test fails."""
    return [line.split(" - ")[0] for line in text.splitlines() if line.startswith("FAILED ")]


def _steps(run: Run, ws: Workspace, pipeline: Pipeline, before: list[str]) -> str:
    """Run the steps in order; return how the run ended: ``finish``, or ``pipeline_stop`` at the first failure.

    The visible suite fails on the case before any change (eight tests, one per open bug), so the last test step
    stops the run only when an edit adds a failure that ``before`` did not have.
    """
    for edit in pipeline.edits:
        _call(run, ws, "read_file", {"path": edit.path})
        result = _call(run, ws, "edit_file", {"path": edit.path, "old": edit.old, "new": edit.new})
        if result.text.startswith("error"):
            run.stop_detail = result.text  # the tool's own message for the step that stopped the run
            return "pipeline_stop"
    text = _call(run, ws, "run_tests", {}).text
    if text.startswith("error") or any(line not in before for line in failing(text)):
        run.stop_detail = text if text.startswith("error") else "new failing tests: " + ", ".join(
            line for line in failing(text) if line not in before)
        return "pipeline_stop"
    done = _call(run, ws, "finish", {"summary": pipeline.summary})
    run.summary = done.summary
    return "finish"


def run_pipeline(task: Task, pipeline: Pipeline, *, case=CASE) -> Run:
    """Run the pipeline for one task on a fresh copy and return the run. The caller scores it, then closes it.

    The failing tests before any change are read by the harness, not as a pipeline step, so they are not counted.
    """
    run = Run(id=f"pipeline-{task.id}", task_id=task.id, case=case, scratch=scratch_copy(case))
    try:
        ws = Workspace(run.scratch)
        run.ended = _steps(run, ws, pipeline, failing(ws.run_tests()))
    except BaseException:
        run.close()
        raise
    return run


@dataclass(frozen=True)
class Shape:
    """A task's properties, as the chapter's decision table states them. ``refused`` marks a change the harness
    itself refuses, which is not a design question."""

    steps_known: bool
    exploration: bool
    wrong_change: str  # "low" or "high"
    auto_check: bool
    person: bool
    refused: bool = False


def design(shape: Shape) -> str:
    """The design that fits a task's shape, by the rules of thumb in chapter 12 (plan section 14). Rules of thumb,
    not measurements: they follow Anthropic's advice to use the simplest design first (S1), and the checks Kim et al.
    keep outside the agent (S4)."""
    if shape.refused:
        return REFUSED
    if shape.person:
        return "agent with gates"
    if shape.steps_known:
        return "fixed pipeline" if shape.auto_check else "one model call"
    return "agent with gates"


REFUSED = "not a design choice: the harness refuses"
ONE_CALL_SHAPE = Shape(True, False, "low", False, False)  # not in the set: a summary of a finished change, read afterwards
TASK_SHAPES: dict[str, Shape] = {  # steps known, exploration, wrong change, auto check, person (the author's judgement)
    "T-01": Shape(True, False, "low", True, False),
    "T-02": Shape(True, False, "low", True, False),
    "T-03": Shape(True, False, "low", True, False),
    "T-04": Shape(True, False, "low", True, False),
    "T-05": Shape(True, False, "low", True, False),
    "T-06": Shape(False, True, "low", True, False),
    "T-07": Shape(False, True, "low", True, False),
    "T-08": Shape(False, True, "low", True, False),
    "T-09": Shape(False, True, "low", True, False),
    "T-10": Shape(True, False, "low", True, False),
    "T-11": Shape(False, True, "high", True, False),
    "T-12": Shape(True, False, "low", True, False),
    "T-13": Shape(False, True, "low", True, False),
    "T-14": Shape(True, False, "low", True, False),
    "T-15": Shape(False, True, "low", True, False),
    "T-16": Shape(True, False, "high", True, True, refused=True),
    "T-17": Shape(False, False, "high", False, True),
    "T-18": Shape(True, False, "high", True, False, refused=True),
    "T-19": Shape(False, False, "high", False, True),
    "T-20": Shape(True, False, "low", True, False),
}


def agent_edit_results(task_id: str) -> tuple[list[str], list[str]]:
    """Replay one task-set run and return the result the tools gave each edit, and each test run, in order.

    The run IDs are numbered as the recording numbered them, so the replayed requests match the recorded ones.
    """
    task = load_tasks(only=[task_id])[0]
    run = run_task(ReplayModel("task-set", task_id), task, V1, max_steps=V1.step_cap, ids=replay_ids(task_id))
    try:
        records = run.trace.records
        edits = [r["brief"] for r in records if r["tool"] == "edit_file"]
        tests = [r["brief"] for r in records if r["tool"] == "run_tests"]
    finally:
        run.close()
    return edits, tests
