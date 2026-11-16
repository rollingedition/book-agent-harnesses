"""Record chapter 1's run: the three-tool set (CH1) on task T-01, with the local model.

    python recordings/chapter_1.py

Writes examples/data/recorded/chapter-1-t01/ with replies.jsonl (raw reply text, one line per step), runs.jsonl,
and a manifest holding the model, its revision, the file's sha256, the prompt's sha256, the sampling pins, the
seed, the threads and the token counts. The recording is never edited by hand: a changed script means a new run.
"""
from __future__ import annotations

import json

import local_model  # sets the path to lib first, then imports the pinned model settings
from recorded import Recording

from lib.case import load_tasks
from lib.loop import run_task
from lib.models import LoggedModel
from lib.prompts import prompt_sha256
from lib.tasks import result_row, score
from lib.tools import CH1
from lib.trace import IdCounter


def main() -> int:
    task = load_tasks(only=["T-01"])[0]
    recording = Recording("chapter-1-t01", prompt_sha256=prompt_sha256(CH1.system, CH1.descriptions()),
                          tool_set=CH1.name, step_cap=CH1.step_cap, **local_model.manifest_fields())
    with recording as out:
        model = LoggedModel(local_model.live_model(), out / "replies.jsonl")
        model.begin(task.id)
        run = run_task(model, task, CH1, max_steps=CH1.step_cap, ids=IdCounter())
        try:
            row = result_row(task, run, score(task, run))
        finally:
            run.close()
        (out / "runs.jsonl").write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
        recording.manifest.update(task=row["task"], ended=row["ended"], done=row["done"], steps=row["steps"],
                                  tool_calls=row["tool_calls"], prompt_tokens=row["prompt_tokens"],
                                  completion_tokens=row["completion_tokens"], check_sha256=row["check_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
