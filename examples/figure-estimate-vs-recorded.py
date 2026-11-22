"""Each recorded step's estimate at three characters per token against the count the model reported for it, with the
line where they are equal. The point rests on the steps over the equal line and on the lowest ratio: no estimate falls
under its count, on the task-set steps the rule was chosen on or on the held-out recording."""
from lib.case import load_tasks
from lib.context import CHARS_PER_TOKEN, PROMPT_BUDGET, Measured, Notes, estimate, notes_toolset
from lib.figures import ACCENT, INK, MUTED, new_figure, save
from lib.loop import Stops, run_task
from lib.models import RECORDED, ReplayModel
from lib.tools import V1
from lib.trace import IdCounter


def pairs(recording, tasks, tools, **limits):
    """(estimate, recorded count) for every request the recorded runs sent; the replay rebuilds each request."""
    ids, out = IdCounter(), []
    for task in tasks:
        model = Measured(ReplayModel(recording, task.id))
        run_task(model, task, tools, ids=ids, **limits).close()
        out += [(estimate(m, t), n) for m, t, n in model.requests]
    return out


task_set = pairs("task-set", load_tasks(), V1, max_steps=V1.step_cap)
held_out = pairs("chapter-5-notes", load_tasks(only=["T-01", "T-02", "T-06"]), notes_toolset(Notes()), max_steps=16,
                 stops=Stops(repeat_limit=3, no_progress_limit=2))
print(f"estimate rule, characters per token: {CHARS_PER_TOKEN}")
for name, rows in (("task-set", task_set), ("held-out", held_out)):
    print(f"{name} steps compared:", len(rows))
    print(f"{name} steps where the estimate is above the recorded count:", sum(e > n for e, n in rows))
    print(f"{name} steps where the estimate is below the recorded count:", sum(e < n for e, n in rows))
    print(f"{name} lowest estimate divided by the recorded count: {min(e / n for e, n in rows):.2f}")
    print(f"{name} highest estimate divided by the recorded count: {max(e / n for e, n in rows):.2f}")
    assert all(e >= n for e, n in rows), f"{name}: the rule should never count fewer tokens than the model did"
print("task-set steps whose estimate is over the prompt budget:", sum(e > PROMPT_BUDGET for e, _ in task_set))

fig, ax = new_figure(height=3.2)
ax.plot([0, 8500], [0, 8500], color=MUTED, linestyle=":", linewidth=1.2, label="estimate equal to the count")
ax.axhline(PROMPT_BUDGET, color=INK, linestyle="--", linewidth=1.0, label=f"prompt budget, {PROMPT_BUDGET} tokens")
for rows, color, marker, size, label in ((task_set, ACCENT, "o", 16, f"task-set steps ({len(task_set)})"),
                                         (held_out, INK, "x", 26, f"held-out steps, chapter-5-notes ({len(held_out)})")):
    ax.scatter([n for _, n in rows], [e for e, _ in rows], s=size, color=color, marker=marker, linewidths=1.2, label=label)
ax.set_xlabel("recorded prompt count, in tokens")
ax.set_ylabel("estimated prompt, in tokens")
ax.set_xlim(0, 8500)
ax.set_ylim(0, 8500)
ax.legend(frameon=False, loc="lower right")
save(fig, "estimate-vs-recorded")
