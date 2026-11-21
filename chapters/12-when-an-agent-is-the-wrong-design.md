---
chapter_id: when-an-agent-is-the-wrong-design
---

# When an agent is the wrong design

By the end of this chapter you can take any task in the case, sort it into a fixed pipeline, a single model call or an agent with gates, and say what the recorded runs show for it. The case gives the first test. Task T-02 is a one-line fix in `unitcraft`, the library whose tasks this chapter sorts by design: negative amounts lose their thousands separator, so `-1234.5 m` should print as `-1,234.50 m`. The recorded run with tool set v1 from [chapter 3](#tool-schemas), the set the task recording was made with, never finished it. It used all {{out:fixed-pipeline-same-task:T-02 agent steps}} of its steps and never called `finish`. The change is one replacement in one function, so the question is whether an agent was ever the right design for it.

## Start with the fixed pipeline {#fixed-pipeline-first}

The first question for T-02 is which steps it needs when nothing in the run has to be decided. Read the formatting module, replace the line that builds the number's text so that negative values keep the separator, run the visible tests, and finish with a sentence describing the change. None of those steps waits on what a model thinks of the file, so none needs a model. A fixed pipeline is a task's list of steps, written as code before the run starts.

Anthropic's engineering post on building agents draws a similar line. It calls a system a workflow when LLMs and tools are orchestrated through predefined code paths, and an agent when an LLM dynamically directs its own processes and tool use ([Anthropic, "Building effective agents"](https://www.anthropic.com/engineering/building-effective-agents), published 19 December 2024). A workflow in that sense still runs a model at its steps. The pipeline in this chapter goes one step further, because none of its steps needs a model. The same post recommends finding the simplest solution possible and adding complexity only when it is needed. The rule this chapter takes from that advice is a rule of thumb, not a measurement: if the steps can be written down before the run, write them down first.

Each pipeline is a list of exact edits and a summary, kept in `lib/pipeline.py`. An [edit](#edit-errors) names the text it replaces and the text that replaces it, and it fails when the old text is not in the file exactly once. The pipeline runs its list through tool set v1, so each call behaves as it does for the agent, and it scores the result with [the same done rule](#score). Only three pipelines are written, for T-02, T-04 and T-05. The example runs them and prints each one beside the agent's stored run on the same task.

[Example: fixed-pipeline-same-task](../examples/fixed-pipeline-same-task.py)

The pipeline finishes all three tasks, and it makes no model call. In this chapter a [step](#the-loop) is a model call, as it is everywhere in the book, so the pipeline has no steps. A pipeline has actions, which are its tool calls, and the line that counts them is `{{out:fixed-pipeline-same-task:T-02 pipeline actions}}` for T-02. The recorded agent on T-02 made `{{out:fixed-pipeline-same-task:T-02 agent steps}}` model calls, one for each step, and its prompt tokens add up to `{{out:fixed-pipeline-same-task:T-02 agent prompt tokens}}`. The pipeline sent no prompt at all. On T-04 and T-05, where the agent finished, the agent still made more model calls than the pipeline had actions, and the example prints both counts for each. Chapter 11 explains why the book counts calls and tokens rather than money ([cost as counts](#cost-not-money)).

Replaying the agent's T-02 run from the recording shows the result of each call. Its edits failed, {{out:fixed-pipeline-same-task:T-02 agent edits failed}}, each with the same message: `error: old text not found in unitcraft/format.py`. The agent read the file again and tried again, with the same error, and it never ran the tests: its test-run count is {{out:fixed-pipeline-same-task:T-02 agent test runs}}. The step cap stopped a run that could not make its change match the file. Nothing in the run checked whether a change had worked, so the count says how long the agent was stuck and nothing about why.

The pipeline fails in its own way too. Its last run gives it an edit for T-04 whose old text does not occur in the file, which is what happens when a file changes under a fixed list. The run ends at that step, after `{{out:fixed-pipeline-same-task:T-04 missing anchor actions}}` actions, with the tool's own message: `{{out:fixed-pipeline-same-task:T-04 missing anchor result}}`. The pipeline does not try another anchor, read the file again or ask anyone. For an edit a person wrote, stopping is the right response, because the file has changed and a person should look.

The stop still has to go somewhere, and a pipeline cannot hand it to a child, because it has none. It can hand the stop to a person, who reads the failed step and decides what to do. Or it can hand the task to an agent, given the step that failed and the file as it now stands. The hybrid, a pipeline first and an agent only on a `pipeline_stop`, is the natural one. The pipeline does the steps that need no judgement, and the agent sees only the part that broke. It starts the agent from a partial state, so the agent's run needs the same gates as any other. We recommend a person when the broken step touches a decision the case gives to a person. We recommend the agent when the step is a known edit that stopped on a changed anchor. This chapter does not measure the hybrid.

Three things limit what the pipeline shows. A person wrote each edit, so the comparison measures what the design costs, not what a pipeline could find alone. The three tasks are the ones whose edits could be named before the run, and nothing here shows how the others would fare. The pipeline also compares failing test ids before and after its edit, because the visible suite already fails before any edit.

**Working rule:** Before you give a model the loop, write the steps out, with the check that follows each one. If every step is known and a check decides the result without a model, build the pipeline and measure it. Decide where its stop goes before the first run: to a person, or to an agent given the failed step.

## When splitting the work helps {#when-to-split}

Once one agent struggles, the next thing people reach for is a second agent. Splitting can look like more care, so the useful question is when it actually helps. Two studies give conditions rather than a verdict.

Tran and Kiela compared one agent with several on multi-hop reasoning, holding the reasoning tokens equal ([Tran and Kiela, arXiv:2604.02460](https://arxiv.org/abs/2604.02460)). The single agent matched or beat the multi-agent systems. Their abstract predicts that multi-agent systems become competitive under two conditions: when a single agent's effective context use is degraded, and when more compute is spent.

Kim et al. ran a controlled comparison across 260 configurations and six agentic benchmarks ([Kim et al., arXiv:2512.08296](https://arxiv.org/abs/2512.08296)). Their abstract says that architecture-task alignment determines collaborative success, and that mismatched coordination degrades performance. The useful reading is conditional: a coordination pattern that helps on one task can hurt on another. Both studies are single papers. Their scope is reasoning and benchmarks, not a maintenance library, so read them as reasons to test a design and not as settled results.

The case can be checked against the first condition, a context the single agent cannot hold. The recording's context window is `{{out:decision-table:context window in the recording, tokens}}` tokens. Its largest single request held `{{out:decision-table:largest request in the recording, prompt tokens}}` prompt tokens, which leaves room under the window, and under the prompt budget that [chapter 5](#window) sets for it. No request in the set reached the window, so no task in the case has a context that forces a split. [Chapter 8](#designs) compares two kinds of split, and it says that this book does not measure a split against one loop. The case therefore gives no number for a split either. The decision table below takes the first condition as its test for splitting, and no row meets it.

**Working rule:** Split a task only when you can name the condition that makes splitting help, such as a context the single agent cannot hold, and when each part has a check that does not depend on the other parts. Otherwise keep one agent, or none.

## What goes wrong when you do use an agent {#failures}

An agent adds places where a run can go wrong, and most of them show only in the record of the run.

Cemri et al. built their taxonomy from 150 traces that expert annotators read closely. They then used an LLM-as-a-judge pipeline, checked against those annotators, to label the more than 1,600 traces in their dataset from seven multi-agent frameworks ([Cemri et al., arXiv:2503.13657](https://arxiv.org/abs/2503.13657), v3). The result is 14 failure modes in three categories: system design issues, inter-agent misalignment, and task verification. The taxonomy is for multi-agent systems, so it maps onto one agent only loosely. This chapter does not map any of its modes onto the case. The malformed tool calls in the replayed run of [chapter 1](#what-goes-wrong) are failures of what the model sends to a tool, and they are visible in the record of that run.

The T-02 run failed by repetition. Its {{out:fixed-pipeline-same-task:T-02 agent steps}} steps were a listing and a run of edits, most of them after a read of the same file, and each edit came back with the same error, because the old text it quoted was not in the file. The step cap ended the run, which is what the budget in [chapter 2](#step-budget) is for, but the cap only stopped the run. The record shows why it never finished: the agent never made a change that matched, and it never checked a change it had not made.

The stop tasks fail in another way. On T-17 and T-19 the agent asked a person a question, and neither run was counted as done. The scorer counts an `ask_user` only when its question names the reason for stopping, and it looks for words such as `half` or `truncat` on T-17 and `dimension`, `length` or `mass` on T-19. T-17 asks for the right rounding for money, and its final question proposes a change to the float-based rounding and asks whether to go ahead. T-19 asks for metres to be turned into kilograms, and its final question offers a special case that assumes a density of 1 and asks which approach the person prefers. Neither question names the reason the scorer looks for. Both runs also tried to edit before they asked. Each edit came back as an error, because its old text was not in the file, and a write to the existing file was refused, so the copies never changed. The record shows that the questions did not name the reason and that the edits failed first. It does not show what a person would have answered, and this chapter does not guess.

T-18 is the other stop task, and its record is a warning about the scorer. The scorer counts its run as done through a word inside a file path, and [chapter 10](#t18-path) explains how. This book leaves the scorer as it is, and it reports T-18 as a limit of the scorer, not as a good handoff.

Reliability is the failure a single run hides. tau-bench defines [pass^k](#score) as the chance that all k independent trials of a task succeed, averaged across tasks ([Yao et al., arXiv:2406.12045](https://arxiv.org/abs/2406.12045)). In its 2024 setup, function-calling agents, gpt-4o among them, succeeded on fewer than half of its tasks, and pass^8 in its retail domain stayed under 25%. One passing run is one trial. This book runs each task once, so it cannot report pass^k, and [chapter 10](#testing-the-agent) describes what it reports in its place.

**Working rule:** Before you trust an agent's design, sort its stopped runs by how they ended and read the record of each kind. A count of failures without their kinds does not say which part to fix, and one passing run does not predict the next.

## The check stays outside the agent {#check-outside}

A run that the agent judges finished is not yet a finished task.

Kim et al. found that architectures without centralized verification tend to propagate errors more than those with centralized coordination. In the paper's own measurement, independent agents amplified trace-level errors 17.2 times, and a centralized orchestrator held that to 4.4 times ([Kim et al.](https://arxiv.org/abs/2512.08296), Section 1 and Table 5). The paper is about several agents. The logic carries over to one: whatever decides that the work is right should not be the part that did the work.

The case applies that logic to its own score. For a fix, the hidden check runs after the run ends, in a copy the agent never sees. The agent may not edit a test to make it pass, and [chapter 10](#testing-the-agent) describes the hidden check.

The stop check is weaker. A stop task is scored from the question the agent wrote, so the agent's own words decide whether the run counts. T-18 shows how little that is worth ([chapter 10](#t18-path)). A check that reads the agent's account of its work is a check the agent can argue with. A visible test the agent can edit tells you what the agent thinks of its change, not what the code does.

**Working rule:** Put the check that decides a task's result where the agent cannot edit it or see it before the run ends. If a finish or a stop depends on the agent's own account of its work, add a check the agent did not write.

## The decision table {#which-design}

The decision table sorts each task by three readings: whether its steps are known before the run, whether a check can decide the result without a person, and whether a person has to say yes. A fourth matter comes before all three, which is whether the harness refuses the change outright. The readings are the author's judgement of each task, not measurements, and the rules are rules of thumb. Each row sits beside the recorded end of that task's run, and no model is called.

The rules run in one order, and the order is the point. First, a change the harness forbids is not a design question. Chapter 6's gate refuses any change under `.github/`, and it refuses a rename that removes a public name, because no yes can lift a rule of that kind ([never-class changes](#never-class)). Second, a person's yes means an agent behind a gate, because the gate must ask before it applies a change. Third, known steps mean a pipeline when a check decides the result, and one model call when no check does. Open steps mean an agent. The order matters for T-16, which the second rule alone would send to a gate, and which the first rule refuses.

[Example: decision-table](../examples/decision-table.py)

The rules give `{{out:decision-table:rows with design 'fixed pipeline'}}` fixed pipelines, `{{out:decision-table:rows with design 'agent with gates'}}` agents with gates, and `{{out:decision-table:rows the harness refuses}}` refusals. The pipelines are T-01 to T-05, T-10, T-12, T-14 and T-20: the edits a person could write before the run, where a test then decides the result. The agents are the open-ended fixes and new functions, T-06 to T-09, T-11, T-13 and T-15, and the two stop tasks T-17 and T-19, where the steps are not known and a person has to decide. The table predicts where to look, not how a run will end.

The recorded agent bears that out only partly. Of the nine pipeline rows, it finished and passed `{{out:decision-table:pipeline rows the recorded agent finished and passed}}` of them: T-04, T-05 and T-14. The other six hit the step cap or stopped with a question. Of the nine agent rows, it finished and passed `{{out:decision-table:agent rows the recorded agent finished and passed}}`, T-09. In all, `{{out:decision-table:rows done in the recording}}` of the twenty runs were done. The rule says a pipeline for the nine rows, and the pipeline has been built and run on only three of them. The other six are predictions, and the record gives them no pipeline result to compare.

T-16 is the row that shows what goes wrong when the order is ignored. Its task renames `parse_quantity` to `parse` and removes the old name. Chapter 6's gate refuses that change, because a removed public name is never the agent's to change, and the gate would refuse it when the diff is read at `finish`. The recorded agent never asked. It tried edits and writes until the step cap, and every one of them failed. An agent behind a gate would spend its whole budget on a change the harness will not apply. So T-16 is a refusal like T-18, and its right ending is a question to the maintainer that asks them to take the rename up as a separate decision. That is the question the scorer's stop word `approv` looks for. Put T-16 among the agent rows and the table is right on paper and wrong in the run.

T-18 is the refusal the other way round. Its edit is under `.github/`, which the gate refuses without a question, so the harness decides it and the design does not. The row records the harness's decision, and the scorer's count for this run is a limit ([chapter 10](#t18-path)), not a good ending.

The one-model-call row needs a case, and the set has none. A single model call fits a step that needs a model's judgement, with no tool and no loop, and whose output a person reads afterwards. Here is one that is not in the set: a summary of T-02's change for the pull request, written from the diff. Its steps are known, since the diff goes in and one paragraph comes out. No check decides whether the paragraph is good, and no yes is needed, because the maintainer reads it after the change. A pipeline cannot write it, because the wording is a judgement a person makes. An agent would add steps that check nothing. Anthropic's post makes a related point: "For many applications, however, optimizing single LLM calls with retrieval and in-context examples is usually enough" ([Anthropic, "Building effective agents"](https://www.anthropic.com/engineering/building-effective-agents)). The rules give `{{out:decision-table:one-call shape, not in the set}}` for that summary, and the example asserts it. No task in the set reaches the row, and the reason is that each task has a check that decides it, a person's yes that sends it to a gate, or steps nobody can name in advance. Every row of the set falls into one of those three, so the count is `{{out:decision-table:rows with design 'one model call'}}`. This chapter has no recorded single reply for the row, and it runs no new model to make one.

**Working rule:** Sort each task in this order before you choose a design: a refusal is a question to a person, not a design; a person's yes is an agent behind a gate; known steps with a check are a pipeline; known steps without a check are a single call whose output a person reads. Open steps are an agent, and then you count its stops by kind, as [chapter 10](#testing-the-agent) does, before you believe the design works.

## Decisions this chapter made {#design-decisions}

- The default for known steps with a check is a pipeline, built and measured before any agent. This follows the advice to start with the simplest design. It is a rule of thumb.
- Pipeline actions and agent model calls are counted apart and never priced, for the reason in [chapter 11](#cost-not-money).
- A refusal comes before a person's yes, because a yes cannot lift a forbidden change. Chapter 6 gives the reason.
- The readings are the author's judgement. A reader who disagrees changes a reading in the example and reruns it, and the rules stay as they are.
- The recorded runs are reported as they ended, and T-02's record is a repeated failure, not a near miss.
- No split is recommended for this case. No task reaches the context condition, and the book does not measure a split against one loop.
- The one-call design has a case, but it is not in the set, and its output is not checked by a test. Only the rule is shown.

What was learned is narrower than the rules suggest. Most of the set's known-step tasks are pipelines on paper, and only three have been run as one. The stop tasks were judged by their questions, and the scorer that did the judging is the weakest part of the case.

**Working rule:** Treat a rule's pipeline as a prediction until a run has measured it, and write down where its stop goes before you build it.
