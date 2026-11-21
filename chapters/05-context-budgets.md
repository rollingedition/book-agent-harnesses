---
chapter_id: context-budgets
---

# Keep the context useful as the task grows

By the end of this chapter you can work out how much room a run's prompt has, estimate a prompt's size when the harness cannot count it exactly, and compact a run's older steps without cutting a tool call away from its result.

The model reads its whole prompt on every step: the system prompt, the tool schemas, the issue, and everything the run has done so far. That prompt has to fit in the window the model was loaded with, and the reply has to fit in the same window. A run that keeps reading files eventually runs out of room.

The problem shows up in the case's longest runs. The maintenance agent for `unitcraft`, the library from [chapter 1](#tools-and-a-loop), reads files, runs the tests and tries an edit, and each read adds a whole file to the prompt. In the recorded task set, T-16 reached the step cap of {{out:compare-v1-v2:task-set step cap}} from [chapter 2](#stop-rules), and its last prompt was the largest of any step in the set. On the recorded counts, that last prompt left {{out:budget-counts-tokens:room left for the reply at the largest step}} tokens to spare, so the recorded runs came closest to the window there. The rest of the chapter covers what the harness must do when a prompt does not fit.

## The window the model has {#window}

The recorded model is Qwen3-4B-Instruct-2507, run from the GGUF file that [chapter 1](#tools-and-a-loop) introduced. The harness loads it with a context of {{out:budget-counts-tokens:load setting, n_ctx, in tokens}} tokens, and the recording's manifest stores that same value as `n_ctx`. That is a load setting the harness chose. The model itself supports far more: its model card gives a native context length of 262,144 tokens ([model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)), read on the card's main branch. This book runs the model in the smaller window, so the number the budget needs is the one the run loads.

The manifest also stores `max_tokens`, the most the reply may take: {{out:budget-counts-tokens:reply reservation, max_tokens, in tokens}} tokens. The reply comes out of the same window as the prompt, so the prompt gets whatever the reply leaves.

The arithmetic is short. {{out:budget-counts-tokens:load setting, n_ctx, in tokens}} tokens, less {{out:budget-counts-tokens:reply reservation, max_tokens, in tokens}} for the reply, leaves {{out:budget-counts-tokens:prompt budget, in tokens}} tokens for everything the model reads on one step. The prompt holds the system prompt, the tool schemas, the issue, the notes, the earlier steps and the last tool result, and all of it counts against that budget. A refusal is a tool result like any other: the harness returns its text to the model as a tool message, so it counts against the budget too. This chapter calls the tokens left for everything the model reads on one step the prompt budget.

[Example: budget-counts-tokens](../examples/budget-counts-tokens.py)

Before it prints anything, the code checks that the recording's manifest names the same window and reply limit as the harness, and it fails the run when they differ. Then it prints the budget and each run's largest prompt against it.

A hosted API has a much larger window. The context editing page of the Anthropic API docs gives 100,000 input tokens as the default trigger for clearing old tool results ([context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing.md)). A trigger at 100,000 tokens would never fire on a window of {{out:budget-counts-tokens:load setting, n_ctx, in tokens}} tokens, so this book takes its budget from the load setting of the model it records, and never from a vendor's default.

**Working rule:** Take the window from the load setting the run used, as the manifest records it, and subtract the reply's limit before you set any budget. Never take it from a model's advertised length or a vendor's default, since a budget copied from a larger model lets a run fill the window before the budget acts.

## Where the recorded runs came closest to the budget {#where-tokens-go}

The recording stores the [prompt count](#token-counts) the model reported for every step, in `replies.jsonl`. The adapter returns that count as `prompt_tokens`, as [chapter 4](#model-adapters) defines the reply, so these are the model's own counts. The harness did not estimate them.

On those counts, no recorded step reached the [prompt budget](#window). Of the {{out:budget-counts-tokens:steps recorded}} recorded steps, {{out:budget-counts-tokens:steps over the prompt budget}} went over it. The largest was T-16's last step, and it left {{out:budget-counts-tokens:room left for the reply at the largest step}} tokens of the window spare once the reply's room was set aside. The check reads the recording and loads no model, so anyone can run it without the hardware that made the recording. The same check, run on any new recording, shows at once whether its prompts still fit the budget, which makes it the first thing to rerun after a model change.

That result says less than it seems. The recorded task set ran tool set v1 with nothing between the loop and the model that could shorten or refuse a prompt. Nothing compacted, and no step was ever cut to fit. The counts show that these prompts fit. They do not show what the harness does when a prompt does not fit, and the rest of this chapter is about that case.

**Working rule:** Compare every step's count with the prompt budget before you read anything into a run.

## Estimate the prompt when the harness can't count it {#estimate}

The exact count comes from the model's own tokenizer, which is part of the model file. This book's examples run offline and never open that file, which is about 2.5 GB and not in the book. So the harness estimates. The estimate counts the characters of every message and of the tool schemas, and divides by three, rounding up: one token for every {{out:estimate-vs-recorded:estimate rule, characters per token}} characters.

We chose three by looking at the task-set recording. The first rule we tried was four characters per token. On the {{out:estimate-vs-recorded:task-set steps compared}} task-set steps, four came out under the true count on {{out:estimate-vs-recorded:task-set with 4 characters per token, steps below the recorded count}} of them. An estimate under the count is the dangerous direction, because the harness would believe it had room the model did not have. So we moved to three.

Each step's estimate can be set against the count the model reported for that same step.

[Example: estimate-vs-recorded](../examples/estimate-vs-recorded.py)

The estimate was above the recorded count on every one of the {{out:estimate-vs-recorded:task-set steps where the estimate is above the recorded count}} steps, and never under it. The ratio of estimate to count ran from {{out:estimate-vs-recorded:task-set lowest estimate divided by the recorded count}} to {{out:estimate-vs-recorded:task-set highest estimate divided by the recorded count}}. The recorded counts include the chat template's tokens, which the estimate does not count, so the average of {{out:estimate-vs-recorded:task-set characters per token, recorded (all steps)}} characters per token is a ratio for this prompt format, not for the text alone.

The price of the safe side is visible too. Three steps had an estimate over the [prompt budget](#window), and on all three the model's own count was within it. A harness that trusted the estimate would have compacted those steps for no reason.

The rule was chosen on the task-set steps, so those steps cannot test it. The held-out check is the chapter-5-notes recording. It was made after the rule was fixed, and its counts were not used to choose it. Its {{out:estimate-vs-recorded:held-out steps compared}} steps show the same pattern: none under the count, with ratios from {{out:estimate-vs-recorded:held-out lowest estimate divided by the recorded count}} to {{out:estimate-vs-recorded:held-out highest estimate divided by the recorded count}}, and {{out:estimate-vs-recorded:held-out characters per token, recorded (all steps)}} characters per token. It is the same model and similar text, so it does not show the rule holds for another tokenizer, another language, or code full of symbols.

**Working rule:** Estimate with three characters per token, and check the estimate against the counts the model reports on the first runs of any new model. If the estimate ever falls under the reported count, use a smaller number of characters per token before you trust the budget.

## Put the last result at the end {#last-result}

Where a fact sits in a prompt matters as well as whether it is there. In a 2023 paper, Liu and colleagues found that performance was often highest when the relevant information came at the beginning or the end of a long input, and dropped when it sat in the middle ([Lost in the Middle](https://arxiv.org/abs/2307.03172)). Those models are older than the one this book records, so the paper describes a pattern in older models, not what Qwen3-4B-Instruct-2507 does with a long prompt.

The book's layout puts the issue and the notes near the start, and the last tool result at the end, where the model reads it last before it replies. That is the book's design rule. No source here says the last result must come last, and the book has not measured this layout on this model. The paper is the reason for the choice. The [compaction example below](#compaction) prints each message the model is sent on the last call, in order: the system prompt, the issue, the summary, the last call and its result.

The layout has a cost. Compaction puts the summary of the older steps between the issue and the last call with its result, which is the middle of the prompt. By the pattern the paper describes, that is where a model would use information least well. The book accepts that cost.

**Working rule:** Put the issue and the notes first and the last tool result last. Treat that as a design choice, and claim a gain only once a run on your own tasks shows one.

## Compact the older steps, and keep the last pair {#compaction}

When the [estimate](#estimate) goes over the [prompt budget](#window), the harness compacts. Compaction here is local: the harness writes the summary itself, and the model never sees it being written. The older steps become one message with one line per step: the call, its arguments cut to 60 characters, and the first line of its result, also cut to 60 characters. The system prompt and the issue stay as they are. The last step, its call and its result, goes in word for word, so the model sees the most recent evidence in full.

Vendors also offer compaction on their servers. Anthropic's compaction guide describes one: compaction "replaces the older turns of a conversation with a summary that Claude writes on the server" ([compaction](https://platform.claude.com/docs/en/build-with-claude/compaction)). Its on-demand form is a beta, behind the header `compact-2026-09-04`. The book does not use the server form, and nothing in this chapter depends on how it behaves. We read that page and did not run it.

The cut rule is the one that matters for a local harness. The vendor's guide to keeping recent turns states it plainly: "Put the cut where no tool call is left open, with each tool call and its result on the same side" ([keeping recent turns](https://platform.claude.com/docs/en/build-with-claude/compaction-keep-recent-turns.md)). A cut that falls on a tool result leaves that result without the call that asked for it, so the harness refuses such a cut.

Four reads and a finish, under a budget of {{out:compact-keeps-last-result:budget, in estimated tokens}} estimated tokens, are enough to cross it. That budget is far below the real {{out:budget-counts-tokens:prompt budget, in tokens}}, on purpose, so that compaction happens on a small task. The real budget is not reached by this task.

[Example: compact-keeps-last-result](../examples/compact-keeps-last-result.py)

The run compacted {{out:compact-keeps-last-result:calls compacted}} older calls, and the last call and its result came through whole: a read of `README.md`, whose result was {{out:compact-keeps-last-result:kept result, in lines}} lines long. The fixed part, the system prompt, the tool schemas and the issue, came to {{out:compact-keeps-last-result:fixed part (system prompt, tool schemas, issue), estimated tokens}} estimated tokens. Compaction cannot cut that part, so a budget under it cannot be met by any compaction.

Two cuts are printed last. A cut before the last result on its own is refused, and a cut before its call is clean. The code asserts both, so a change to either fails the run.

**Working rule:** Keep the last call and its result together, refuse any cut that falls on a tool result, and check that the fixed part fits the budget before you rely on compaction to make the rest fit.

## Keep notes outside the context {#notes}

Compaction loses detail by design. Anthropic's engineering post on context engineering puts it as a choice: "The art of compaction lies in the selection of what to keep versus what to discard, as overly aggressive compaction can result in the loss of subtle but critical context whose importance only becomes apparent later" ([Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)). The same post describes the way round it, with notes kept outside the window, and it reports no measurement of them.

The harness adds a `note` tool: the model writes one line per fact, and the harness sends the notes after the issue at every step. Compaction does not cut them, because they are not part of the older steps. A fact the model writes as a note survives every compaction. A fact that stays only in an older result is kept at most as the first line of that result.

[Example: notes-survive](../examples/notes-survive.py)

This example is a script, not the model. A `ScriptedModel` reads four files and writes three notes, each one right after the read it came from. The fact sits on line 18 of the file, and the summary keeps only the file's first line, so the summary's line for that read has the docstring and not the fact. The run compacted {{out:notes-survive:compactions}} times. All {{out:notes-survive:notes written}} notes are whole in the notes block of the last request, and {{out:notes-survive:lines in the notes block that name the fact (rstrip)}} of those lines names the fact. Each note states something the run had read in the case, so a reader can check each one against the case files.

That shows the mechanism. It does not show that a model will write the notes. The next section checks that on a recording of the model.

**Working rule:** Write a fact that a later step needs into a note, not only into the summary. A summary keeps a selection, and the notes are the one place the book keeps a fact whole.

## What the recorded model did with the budget {#recorded-runs}

The recording `chapter-5-notes` was made with tool set v2 from [chapter 3](#tool-schemas), the note tool, and the stop rules from [chapter 2](#stop-rules). Its three runs are T-01, T-02 and T-06. Seven task-set runs reached the step cap of {{out:compare-v1-v2:task-set step cap}} ({{out:stop-rules-over-task-set:step cap without the rules, tasks}}), and the recording's script names these three as the long runs that each hit that cap. It does not run the other four. We replayed the three runs with compaction on, to see what the model did with the tools and the budget.

[Example: recorded-context-use](../examples/recorded-context-use.py)

The model wrote no notes on any of the three runs, and no run was compacted. The largest prompt the estimate saw was {{out:recorded-context-use:largest estimated prompt over the three runs, in tokens}} tokens, and the largest the model reported was {{out:recorded-context-use:largest recorded prompt over the three runs, in tokens}}. Both are under the [prompt budget](#window).

Each run ended before its context came near the budget, and none of them passed its check. T-01 ended as `{{out:recorded-context-use:T-01 ended}}`, when the model asked the person a question. T-01 is a fix task, so that question was a wrong handoff. T-02 ended as `{{out:recorded-context-use:T-02 ended}}`, when the model called finish, and its check did not pass. T-06 ended as `{{out:recorded-context-use:T-06 ended}}`, which is the stop rule from [chapter 2](#stop-rules): two edits in a row left the test counts unchanged. So the model stopped two runs itself, both wrongly, and a stop rule stopped the third. Printed run by run, the check results give {{out:recorded-context-use:runs whose check passed}} passes out of the three.

Three runs on three tasks show what happened on those tasks, and nothing about the other seventeen. These runs test neither the budget nor the notes.

**Working rule:** Before you judge a budget or a tool by a recording, check how each run ended. A run that stops early never tests the budget, and a model that never calls a tool never tests the tool.

## Measure the effect instead of quoting it {#measure}

A July 2025 technical report from Chroma, "Context Rot" by Hong, Troynikov and Huber, found that "model performance varies significantly as input length changes, even on simple tasks" ([Context Rot](https://www.trychroma.com/research/context-rot)). The report evaluates 18 LLMs from several vendors, including Qwen3, on its own tasks. This chapter does not re-run those tasks, so it quotes no effect size from them.

The book measures its own runs instead. [Chapter 10](#testing-the-agent) runs the task set on two harness versions and compares them as counts of finished tasks. [Harness v2](#v1-v2) adds the budget among several other changes, so that comparison cannot credit the budget alone. A child run in [chapter 8](#subagents-and-handoffs) keeps a budget of its own, counted on its own steps.

Each example here measures something else. The budget example measures where the recorded prompts sat, and the compaction and notes examples measure what the harness keeps. None measures how length affects a model's answers, so this chapter does not say that a long prompt costs accuracy.

**Working rule:** Measure how a budget changes your own task set, with the counts the runs report, before you claim that it helps. Quote a published effect only with its setup and its source, and only as that report's result.

## How a budget goes wrong, and how to notice {#production}

Four things go wrong with budgets in practice, and each one can be noticed.

The first is a changed model. A new model may have a different window, tokenizer or reply limit. The budget is then wrong without any error, because the check still runs and still passes against the old number. You notice it when the window in the recording's manifest no longer matches the constant the harness uses, so keep the two linked and fail a run when they differ. The [window section](#window) explains the check.

The second is an estimate that drifts. The estimate is only as good as the characters-per-token rule for the model and the text in front of it. The reply already carries the model's own count, so compare the two on every step of the first real runs, and log the pairs. An estimate under the count is the sign to act on, because the harness then believes it has room it does not have.

The third is a summary that drops what a later step needs. A compacted run can call the same tool again, because the first result is now one line in a summary. The stop rules from [chapter 2](#stop-rules) catch exact repeats, but a near-repeat, such as a read of the same file with a slightly different path, passes them. Count the reads a run makes of the same file, and treat a repeat as a sign that the summary lost something.

The fourth is a notes block that grows. The notes are sent at every step and compaction never cuts them, and nothing caps a note's length or how many there are. A run that writes many notes grows its fixed part until compaction cannot meet the budget. The context counts the calls still over the budget after compaction in `over_budget`, and a count above zero is the sign.

**Working rule:** Log the estimate and the reported count on every step of a real run, and treat an estimate under the count as a fault. When a run asks for a file that its own summary already covers, check what the summary kept before the run reads the file again.

## Decisions this chapter made {#what-this-chapter-decided}

- The prompt budget is the load setting less the reply's room, and it follows the load setting, not the model's advertised length.
- The harness estimates the prompt at three characters per token. The task-set steps chose that rule, and the later chapter-5-notes recording, which did not choose it, shows the same pattern.
- Compaction is local and deterministic, so a replayed run compacts exactly as the original did. The older steps become one line each, and the last call and its result are kept word for word. A cut that falls on a tool result is refused.
- The notes are a tool the model may use. They are sent after the issue at every step, so compaction never cuts them, and the model decides whether to write them.
- The book does not use the vendor's server-side compaction.

The recordings show that the prompts fit, and that the estimate stayed above the count on both sets of steps. [Chapter 10](#testing-the-agent) compares two harness versions as counts, and it cannot credit the budget alone.

**Working rule:** Name the runs a budget or a tool was tested on. A claim about a budget that no run reached is a claim about the design, not about the model.
