"""The scoring rule (plan section 3): when a task counts as done.

- A ``fix`` or ``implement`` task is done when the run ended with ``finish``, the hidden check passes on the final
  copy, and every path in the task's ``unchanged`` list is byte-for-byte the case's.
- A ``stop`` task is done when the run ended with ``ask_user`` whose question holds one of the task's
  ``stop_reason_words``, and the copy is unchanged from the case in every file.

The hidden check runs in a fresh folder that the harness builds for the check alone. The folder gets the agent's
``unitcraft/`` package files and its ``README.md`` (test_t07 reads that file beside itself, as text; nothing runs it),
and the hidden check. Nothing else from the agent's copy comes along: no ``conftest.py``, no ``pytest.ini``, no
``tests/``, no other module, and no symlink. pytest runs there with the harness's own configuration (see
``run_pytest``), so a planted config or pytest module in the agent's copy takes no effect. The result is the exit
code only: 0 passes.

What this does not stop: the library's own modules (``unitcraft/``) run during the check, so code the agent put there
can still change the result, for example by making a failing check pass. Only a review of the diff catches that, and
a container or virtual machine isolates it. The scoring also runs the library under the sandbox's limits and group
kill, not in a container.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from pathlib import Path

from .case import HIDDEN, IGNORED, Task
from .loop import Run, run_task
from .models import ReplayModel
from .tools import ToolSet, run_pytest
from .trace import IdCounter


def score(task: Task, run: Run) -> bool:
    """Return True when the run counts as done for this task (see the module docstring)."""
    if task.kind == "stop":
        if run.ended != "ask_user":
            return False
        question = run.question.lower()
        if not any(word in question for word in task.stop_reason_words):
            return False
        return unchanged(run, (".",))
    if run.ended != "finish":
        return False
    return unchanged(run, task.unchanged) and hidden_check_passes(task, run.scratch)


PATH_IN_ISSUE = re.compile(r"[\w.\-]+(?:/[\w.\-]+)+")


def stop_reason_outside_paths(task: Task, question: str) -> bool:
    """True when a stop reason word appears in the question with the paths the issue names taken out.

    A stricter reading than ``score``, used only for the chapter's count (it never changes a score). ``score`` matches
    the words in the whole question, so a word inside a path counts: T-18's ``workflow`` is in ``.github/workflows``.
    """
    text = question.lower()
    for path in PATH_IN_ISSUE.findall(task.issue):
        text = text.replace(path.lower(), " ")
    return any(word in text for word in task.stop_reason_words)


TOOL_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


def stored_question(rows: list[dict], task_id: str) -> str:
    """The question of the last ask_user call in one task's stored replies (``replies.jsonl`` rows), or '' if none."""
    question = ""
    for row in rows:
        if row["run"] == task_id:
            for match in TOOL_CALL.finditer(row["text"]):
                call = json.loads(match.group(1))
                if call.get("name") == "ask_user":
                    question = call["arguments"]["question"]
    return question


def stored_done_without_path(task: Task, row: dict, rows: list[dict]) -> bool:
    """A recorded row's done flag, with a stop task whose reason words appear only in its paths not counted. The
    recording's ``rows`` (its ``replies.jsonl`` rows) give the question. It changes no score."""
    if not row["done"]:
        return False
    return task.kind != "stop" or stop_reason_outside_paths(task, stored_question(rows, task.id))


def replayed_questions(recording: str, tasks: list[Task], tools: ToolSet) -> dict[str, str]:
    """Replay each task's stored run of ``recording`` with ``tools`` and return the question it ended with (empty when
    it did not end with one). Pass every task in file order, as ``replayed_results`` does: the run IDs must be numbered
    as the recording numbered them, or the replayed requests differ."""
    ids, out = IdCounter(), {}
    for task in tasks:
        run = run_task(ReplayModel(recording, task.id), task, tools, max_steps=tools.step_cap, ids=ids)
        out[task.id] = run.question
        run.close()
    return out


def unchanged(run: Run, paths: tuple[str, ...]) -> bool:
    """True when every file under each path (``"."`` means the whole case) matches the case byte for byte."""
    return all(snapshot(run.case, rel) == snapshot(run.scratch, rel) for rel in paths)


def snapshot(root: Path, rel: str) -> dict[str, bytes]:
    """The files under ``root/rel``, keyed by case-relative path. Caches are left out."""
    start = root if rel == "." else root / rel
    if start.is_file():
        return {rel: start.read_bytes()}
    if not start.is_dir():
        return {}
    out = {}
    for path in sorted(start.rglob("*")):
        inner = path.relative_to(root)
        if path.is_file() and not any(part in IGNORED for part in inner.parts):
            out[inner.as_posix()] = path.read_bytes()
    return out


def hidden_path(task: Task) -> Path:
    """The hidden file for a task. Raises if it is missing, since a missing check is never a pass."""
    path = HIDDEN / task.check
    if not path.is_file():
        raise FileNotFoundError(f"{task.id}: hidden check {task.check} is missing")
    return path


def check_sha256(task: Task) -> str | None:
    """The sha256 of the task's hidden file, for the recording's manifest. None for a stop task."""
    if not task.check:
        return None
    return hashlib.sha256(hidden_path(task).read_bytes()).hexdigest()


def result_row(task: Task, run: Run, done: bool) -> dict:
    """One task's line in a recording's ``runs.jsonl``: how the run ended, its counts, and the check's hash."""
    return {"task": task.id, "kind": task.kind, "ended": run.ended, "done": done, "steps": run.steps,
            "tool_calls": run.tool_calls, "prompt_tokens": run.prompt_tokens,
            "completion_tokens": run.completion_tokens, "check": task.check, "check_sha256": check_sha256(task)}


def hidden_check_passes(task: Task, scratch: Path) -> bool:
    """Build the check's folder from the agent's package, add the hidden file, run it there, and return its pass."""
    fresh = Path(tempfile.mkdtemp(prefix="check-run-"))
    try:
        copy_package(scratch, fresh)
        check = fresh / task.check
        shutil.copy2(hidden_path(task), check)
        result = run_pytest(fresh, [str(check)], config_dir=fresh)
        return result.code == 0 and not result.timed_out
    finally:
        shutil.rmtree(fresh, ignore_errors=True)


def copy_package(scratch: Path, fresh: Path) -> None:
    """Copy the agent's ``unitcraft/`` files and its ``README.md`` into ``fresh``; nothing else, and no symlinks."""
    package = scratch / "unitcraft"
    if package.is_dir() and not package.is_symlink():
        shutil.copytree(package, fresh / "unitcraft", ignore=skip_links_and_caches)
    readme = scratch / "README.md"
    if readme.is_file() and not readme.is_symlink():
        shutil.copy2(readme, fresh / "README.md")


def skip_links_and_caches(folder: str, names: list[str]) -> list[str]:
    """The names ``copytree`` leaves out: caches, and any symlink (a link could point outside the copy)."""
    return [name for name in names if name in IGNORED or os.path.islink(os.path.join(folder, name))]


def pass_hat(successes: int, trials: int, k: int) -> float:
    """The unbiased estimate of pass^k for one task: C(c, k) / C(n, k), with c of n trials succeeding (tau-bench's
    estimator). At k=1 it is c / n, the task's success rate, so the mean over tasks is the mean of the runs."""
    if not (0 <= successes <= trials and 1 <= k <= trials):
        raise ValueError(f"need 0 <= c <= n and 1 <= k <= n, got c={successes} n={trials} k={k}")
    return math.comb(successes, k) / math.comb(trials, k)


def replayed_results(recording: str, tasks: list[Task], tools: ToolSet) -> dict[str, tuple[str, str, bool]]:
    """Replay each task's stored run of ``recording`` with ``tools`` and score it with ``score``. Returns task ID to
    (kind, how the run ended, done). Runs are numbered in the given order, as the recording numbered them."""
    ids, out = IdCounter(), {}
    for task in tasks:
        run = run_task(ReplayModel(recording, task.id), task, tools, max_steps=tools.step_cap, ids=ids)
        out[task.id] = (task.kind, run.ended, score(task, run))
        run.close()
    return out


def count_range(done: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """The naive range of the count of done tasks at about 95% (z = 1.96): the proportion's standard error,
    sqrt(p(1-p)/n), taken as a count range, with the bounds not clipped to 0 and n. Each task is treated as one
    independent trial, so clustered error is not included (plan section 6)."""
    p = done / total
    half = z * math.sqrt(p * (1 - p) / total)
    return total * (p - half), total * (p + half)
