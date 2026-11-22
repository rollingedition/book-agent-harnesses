"""The task-set recording's 20 runs, each replayed as recorded and again with both stop rules, drawn as steps per task.
The rules shorten the stuck runs and leave the done runs at the same steps, which the last assert checks."""
from lib.case import load_tasks
from lib.figures import ACCENT, INK, MUTED, new_figure, save
from lib.loop import Stops, run_task
from lib.models import ReplayModel
from lib.tasks import score
from lib.tools import V1
from lib.trace import IdCounter


def replay(stops: Stops) -> dict:
    """Each task's (steps, done) in file order, so the run IDs match the recording's."""
    ids, out = IdCounter(), {}
    for task in load_tasks():
        run = run_task(ReplayModel("task-set", task.id), task, V1, max_steps=V1.step_cap, ids=ids, stops=stops)
        out[task.id] = (run.steps, score(task, run))
        run.close()
    return out


# Three identical calls in a row, and two edits that leave the counts where they were.
plain, ruled = replay(Stops()), replay(Stops(repeat_limit=3, no_progress_limit=2))
tasks = list(plain)
x = list(range(1, len(tasks) + 1))
steps_plain, steps_ruled = [[runs[t][0] for t in tasks] for runs in (plain, ruled)]
done = [i for i, t in enumerate(tasks) if plain[t][1]]
assert all(ruled[tasks[i]] == plain[tasks[i]] for i in done), "a done run changed with the rules"

print("task set step cap:", V1.step_cap)
print("runs:", len(tasks))
print("runs the rules shortened:", sum(r < p for r, p in zip(steps_ruled, steps_plain)))
print("steps saved in all:", sum(steps_plain) - sum(steps_ruled))
print("done runs:", len(done))
print("steps of the done runs as recorded:", sum(steps_plain[i] for i in done))
print("steps of the done runs with both rules:", sum(steps_ruled[i] for i in done))

fig, (ax, strip) = new_figure(rows=2, height=3.9)
# A thin line joins each task's two counts: a drop is a shortened run, a single point an unchanged one.
ax.vlines(x, steps_ruled, steps_plain, color=MUTED, linewidth=0.8)
ax.plot(x, steps_plain, linestyle="none", marker="o", markersize=5, markerfacecolor="none", color=MUTED,
        label="as recorded")
ax.plot(x, steps_ruled, linestyle="none", marker="s", markersize=4, color=ACCENT, label="with both rules")
ax.axhline(V1.step_cap, color=INK, linestyle="--", linewidth=1.0, label=f"step cap, {V1.step_cap} steps")
ax.set(ylabel="steps in the run", ylim=(0, V1.step_cap + 6))   # headroom above the cap line holds the legend
ax.legend(frameon=False, loc="upper center", ncol=3)
# The done runs sit on their own row, so which runs passed reads without the colour or the line.
strip.plot([x[i] for i in done], [0] * len(done), linestyle="none", marker="^", markersize=6, color=INK)
strip.set(yticks=[0], yticklabels=["done"], ylim=(-1, 1), xticks=x, xticklabels=tasks, xlabel="task, in file order")
strip.tick_params(axis="x", labelrotation=90, labelsize=7)
save(fig, "steps-with-and-without-rules")
