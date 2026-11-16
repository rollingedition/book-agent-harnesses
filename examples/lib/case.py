"""The case: the library the agent maintains, the task list, and a scratch copy for each run.

The agent never works on the case itself. ``scratch_copy`` makes a fresh copy in a temporary folder outside the
book for each run, and every write the agent makes lands in that copy only. Paths printed anywhere are
case-relative (``unitcraft/format.py``); the temporary folder's own path is never printed.
"""
from __future__ import annotations

import shutil
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
CASE = DATA / "case"
TASKS = DATA / "tasks.toml"
HIDDEN = DATA / "hidden"
IGNORED = ("__pycache__", ".pytest_cache")
KINDS = ("fix", "implement", "stop")


@dataclass(frozen=True)
class Task:
    """One task from ``tasks.toml``: the issue the agent reads, and what counts as done."""

    id: str
    kind: str
    issue: str
    check: str
    unchanged: tuple[str, ...]
    stop_reason_words: tuple[str, ...] = ()


def load_tasks(path: Path = TASKS, only: list[str] | None = None) -> list[Task]:
    """Read the task list in file order, keeping only the ids in ``only`` when it is given."""
    with path.open("rb") as handle:
        rows = tomllib.load(handle).get("task", [])
    tasks = []
    for row in rows:
        if row["kind"] not in KINDS:
            raise ValueError(f"{row['id']}: kind must be one of {', '.join(KINDS)}")
        if row["kind"] != "stop" and not row["check"]:
            raise ValueError(f"{row['id']}: a {row['kind']} task needs a hidden check")
        if row["kind"] == "stop" and not row.get("stop_reason_words"):
            raise ValueError(f"{row['id']}: a stop task needs stop_reason_words")
        tasks.append(Task(
            id=row["id"],
            kind=row["kind"],
            issue=row["issue"],
            check=row["check"],
            unchanged=tuple(row["unchanged"]),
            stop_reason_words=tuple(w.lower() for w in row.get("stop_reason_words", [])),
        ))
    if only is not None:
        wanted = set(only)
        missing = wanted - {t.id for t in tasks}
        if missing:
            raise ValueError(f"no such task: {', '.join(sorted(missing))}")
        tasks = [t for t in tasks if t.id in wanted]
    return tasks


def case_files(root: Path) -> list[str]:
    """List the files under ``root`` as case-relative POSIX paths, sorted."""
    found = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and not any(part in IGNORED for part in rel.parts):
            found.append(rel.as_posix())
    return sorted(found)


def scratch_copy(root: Path = CASE) -> Path:
    """Copy the case into a new temporary folder and return the folder. The caller removes it when done."""
    target = Path(tempfile.mkdtemp(prefix="case-run-"))
    shutil.copytree(root, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*IGNORED))
    return target
