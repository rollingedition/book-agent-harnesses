"""Record chapter 5's harness on three long tasks: the v2 tools with ``note``, chapter 2's stop rules, and chapter 5's
budget (the 8192 window less the reply's 1024 tokens) with the local compaction.

    python recordings/chapter_5.py

Each reply is appended to replies.jsonl as it arrives, raw text, with its request's sha256. The compaction runs in
front of the model (``Compacting``), so the requests the recording hashes are the ones the replay rebuilds. Each
task's notes are kept in notes/ beside the replies. The recording copies into examples/data/recorded/chapter-5-notes/
only when it finishes (see recordings/recorded.py). This writes nothing else into the book.
"""
from __future__ import annotations

import json

import local_model  # sets the path to lib first, then imports the pinned model settings
from recorded import Recording

from lib.case import load_tasks
from lib.context import CHARS_PER_TOKEN, PROMPT_BUDGET, REPLY, WINDOW, Compacting, Context, Notes, notes_toolset
from lib.loop import Stops, run_task
from lib.models import LoggedModel
from lib.prompts import prompt_sha256
from lib.tasks import result_row, score
from lib.trace import IdCounter

TASKS = ["T-01", "T-02", "T-06"]  # the long runs: each hit the step cap in the task-set recording
RULES = Stops(repeat_limit=3, no_progress_limit=2)


def main() -> int:
    tools = notes_toolset(Notes())
    fields = local_model.manifest_fields()
    recording = Recording("chapter-5-notes", prompt_sha256=prompt_sha256(tools.system, tools.descriptions()),
                          tool_set=tools.name, step_cap=tools.step_cap,
                          stops={"repeat_limit": RULES.repeat_limit, "no_progress_limit": RULES.no_progress_limit},
                          context={"window": WINDOW, "reply": REPLY, "prompt_budget": PROMPT_BUDGET,
                                   "chars_per_token": CHARS_PER_TOKEN, "compaction": "local, deterministic"},
                          tasks_run=TASKS, **fields)
    with recording as out:
        (out / "notes").mkdir()
        model = LoggedModel(local_model.live_model(), out / "replies.jsonl")
        ids, rows = IdCounter(), []
        for task in load_tasks(only=TASKS):
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
            rows.append(row)
        with (out / "runs.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        recording.manifest["tasks"] = rows
        recording.manifest["done_count"] = sum(1 for row in rows if row["done"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
