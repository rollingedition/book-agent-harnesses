"""Record the v1 harness on the task set: every task in examples/data/tasks.toml, run with the local model.

    python recordings/task_set.py                       # all tasks, from the start
    python recordings/task_set.py --only T-01,T-02      # some tasks (this replaces the recording's other tasks)
    python recordings/task_set.py --fresh false         # resume: keep finished tasks, record the rest again

Each reply is appended to replies.jsonl as it arrives, raw text, with its request's sha256. A task's line goes to
runs.jsonl when its run ends. A stop leaves the scratch folder as it is; a resume keeps the finished tasks' replies
and drops any unfinished task's replies, since that task is recorded again from its first step. The recording copies
into examples/data/recorded/task-set/ only when it finishes (see recordings/recorded.py).

This writes nothing else into the book. Recordings run for hours on this machine: run it in the background.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import local_model  # sets the path to lib first, then imports the pinned model settings
from recorded import Recording

from lib.case import load_tasks
from lib.loop import run_task
from lib.models import LoggedModel
from lib.prompts import prompt_sha256
from lib.tasks import result_row, score
from lib.tools import V1
from lib.trace import IdCounter


def read_jsonl(path: Path) -> list[dict]:
    """Read JSON lines, skipping a line cut off by a stop."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def keep_finished(out: Path) -> set[str]:
    """Return the ids of finished tasks, and rewrite replies.jsonl with only their replies."""
    finished = {row["task"] for row in read_jsonl(out / "runs.jsonl")}
    kept = [row for row in read_jsonl(out / "replies.jsonl") if row["run"] in finished]
    with (out / "replies.jsonl").open("w", encoding="utf-8") as handle:
        for row in kept:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return finished


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record the v1 harness on the task set.")
    parser.add_argument("--only", help="comma-separated task ids, for example T-01,T-02")
    parser.add_argument("--fresh", choices=["true", "false"], default="true",
                        help="false resumes an earlier, stopped recording in the scratch area")
    args = parser.parse_args(argv)

    tasks = load_tasks(only=args.only.split(",") if args.only else None)
    fields = local_model.manifest_fields()
    recording = Recording("task-set", prompt_sha256=prompt_sha256(V1.system, V1.descriptions()),
                          fresh=args.fresh == "true", tool_set=V1.name, step_cap=V1.step_cap, **fields)
    with recording as out:
        finished = keep_finished(out) if args.fresh == "false" else set()
        model = LoggedModel(local_model.live_model(), out / "replies.jsonl")
        ids = IdCounter()
        for task in tasks:
            if task.id in finished:
                continue
            model.begin(task.id)
            run = run_task(model, task, V1, max_steps=V1.step_cap, ids=ids)
            try:
                row = result_row(task, run, score(task, run))
            finally:
                run.close()
            with (out / "runs.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        recording.manifest["tasks"] = sorted(read_jsonl(out / "runs.jsonl"), key=lambda r: r["task"])
        recording.manifest["done_count"] = sum(1 for r in recording.manifest["tasks"] if r["done"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
