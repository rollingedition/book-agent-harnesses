"""Record the v2 harness on the task set: all 20 tasks in examples/data/tasks.toml, run with the local model.

    python recordings/task_set_v2.py                      # all 20 tasks, from the start
    python recordings/task_set_v2.py --only T-01,T-02     # some tasks (this replaces the recording's other tasks)
    python recordings/task_set_v2.py --fresh false        # resume: keep finished tasks, record the rest again

The harness is chapter 5's configuration (plan section 18), the one recordings/chapter_5.py uses: the v2 tools with
``note`` (lib/context.py's notes_toolset), chapter 2's stop rules, and the prompt budget of 7168 tokens (the 8192
window less the 1024 tokens reserved for the reply) with the local compaction in front of the model. The step cap is
16. The tasks, the pins and the scorer are task_set.py's: only the harness differs.

Each reply is appended to replies.jsonl as it arrives, raw text, with its request's sha256. The requests are the ones
after compaction, so a replay rebuilds them. Each task's notes are kept in notes/ beside the replies. A task's line goes
to runs.jsonl when its run ends. Run IDs count every task in file order, finished or not, so a resumed task gets the
ID it had in a full run, as replay expects. A resume keeps the finished tasks' replies and notes and drops an
unfinished task's, since that task is recorded again from its first step. The recording copies into
examples/data/recorded/task-set-v2/ only when it finishes (see recordings/recorded.py). This writes nothing else into
the book. Recordings run for hours on this machine: run it in the background.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import local_model  # sets the path to lib first, then imports the pinned model settings
from recorded import Recording

from lib.case import load_tasks
from lib.context import CHARS_PER_TOKEN, PROMPT_BUDGET, REPLY, WINDOW, Compacting, Context, Notes, notes_toolset
from lib.loop import Stops, run_task
from lib.models import LoggedModel
from lib.prompts import prompt_sha256
from lib.tasks import result_row, score
from lib.trace import IdCounter

RULES = Stops(repeat_limit=3, no_progress_limit=2)


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
    """Return the ids of finished tasks. Rewrites replies.jsonl and notes/ with only the finished tasks' files."""
    finished = {row["task"] for row in read_jsonl(out / "runs.jsonl")}
    kept = [row for row in read_jsonl(out / "replies.jsonl") if row["run"] in finished]
    with (out / "replies.jsonl").open("w", encoding="utf-8") as handle:
        for row in kept:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    for path in (out / "notes").glob("*.md"):
        if path.stem not in finished:
            path.unlink()
    return finished


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record the v2 harness on the task set.")
    parser.add_argument("--only", help="comma-separated task ids, for example T-01,T-02")
    parser.add_argument("--fresh", choices=["true", "false"], default="true",
                        help="false resumes an earlier, stopped recording in the scratch area")
    args = parser.parse_args(argv)

    selected = set(args.only.split(",")) if args.only else None
    tools = notes_toolset(Notes())  # the schemas and system prompt every request carries, for the manifest's hash
    fields = local_model.manifest_fields()
    recording = Recording(
        "task-set-v2", prompt_sha256=prompt_sha256(tools.system, tools.descriptions()),
        fresh=args.fresh == "true", tool_set=tools.name, step_cap=tools.step_cap,
        stops={"repeat_limit": RULES.repeat_limit, "no_progress_limit": RULES.no_progress_limit},
        context={"window": WINDOW, "reply": REPLY, "prompt_budget": PROMPT_BUDGET,
                 "chars_per_token": CHARS_PER_TOKEN, "compaction": "local, deterministic"},
        **fields)
    with recording as out:
        finished = keep_finished(out) if args.fresh == "false" else set()
        (out / "notes").mkdir(exist_ok=True)
        model = LoggedModel(local_model.live_model(), out / "replies.jsonl")
        ids = IdCounter()
        for task in load_tasks():  # every task in file order, so the run IDs match a full run's numbering
            if task.id in finished or (selected is not None and task.id not in selected):
                ids.next("run")  # this task's run ID is still used up, as in a full run
                continue
            notes = Notes(out / "notes" / f"{task.id}.md")
            context = Context(notes=notes)
            model.begin(task.id)
            run = run_task(Compacting(model, context), task, notes_toolset(notes), max_steps=tools.step_cap,
                           ids=ids, stops=RULES)
            try:
                row = result_row(task, run, score(task, run))
            finally:
                run.close()
            row.update(compactions=context.compactions, over_budget=context.over_budget, notes=len(notes.lines))
            with (out / "runs.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        recording.manifest["tasks"] = sorted(read_jsonl(out / "runs.jsonl"), key=lambda r: r["task"])
        recording.manifest["done_count"] = sum(1 for r in recording.manifest["tasks"] if r["done"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
