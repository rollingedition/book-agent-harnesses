"""Each recorded run as one point: its steps against its prompt tokens, summed over the run, marked by how it ended.
The point rests on the step-capped runs sitting in one column at the cap, above every other run, and on the prompt
tokens per step, which grow with the steps."""
from lib.figures import ACCENT, INK, MUTED, new_figure, save
from lib.models import load_recording

manifest, _ = load_recording("task-set")
tasks = sorted(manifest["tasks"], key=lambda t: (t["steps"], t["task"]))  # ties in steps are broken by task ID
cap = manifest["step_cap"]
capped = [t for t in tasks if t["ended"] == "step_cap"]
assert all(t["steps"] == cap for t in capped), "a step-capped run stops at the cap"
assert min(t["prompt_tokens"] for t in capped) > max(t["prompt_tokens"] for t in tasks if t not in capped)


def share(key):  # the step-capped runs' part of the whole set, in per cent
    return 100 * sum(t[key] for t in capped) / sum(t[key] for t in tasks)


shortest = tasks[0]
longest = max(tasks, key=lambda t: (t["steps"], t["prompt_tokens"]))  # the most steps, then the larger prompt total

fig, ax = new_figure(height=3.2)
for ending, color, marker in (("finish", INK, "o"), ("ask_user", MUTED, "s"), ("step_cap", ACCENT, "^")):
    group = [t for t in tasks if t["ended"] == ending]
    ax.scatter([t["steps"] for t in group], [t["prompt_tokens"] for t in group], color=color, marker=marker, s=24,
               label=f"ended with {ending}, {len(group)} runs")
ax.set_xlabel("steps the run took")
ax.set_ylabel("prompt tokens, summed over its steps")
ax.set_xlim(3, 17)
ax.set_xticks(range(4, 17, 2))
ax.set_ylim(0, 65000)
ax.legend(frameon=False, loc="upper left")
save(fig, "tokens-against-steps")

print(f"runs drawn: {len(tasks)}")
print(f"step cap, in steps: {cap}")
print(f"step-capped share of steps: {share('steps'):.1f}%")
print(f"step-capped share of prompt tokens: {share('prompt_tokens'):.1f}%")
print(f"shortest run, task: {shortest['task']}")
print(f"shortest run, steps: {shortest['steps']}")
print(f"shortest run, prompt tokens per step: {shortest['prompt_tokens'] // shortest['steps']}")
print(f"longest run, task: {longest['task']}")
print(f"longest run, steps: {longest['steps']}")
print(f"longest run, prompt tokens per step: {longest['prompt_tokens'] // longest['steps']}")
