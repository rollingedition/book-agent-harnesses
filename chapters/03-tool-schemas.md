---
chapter_id: tool-schemas
---

# Give the model tools it can't misuse

By the end of this chapter you can give a model tools whose arguments the harness checks before any tool runs, and write refusals the model can act on.

The agent's job is to fix `unitcraft`, a small Python library that formats and converts quantities. Its edits are where this chapter's problem shows, since one missing quote makes one fail. The agent works on a scratch copy of the library. In [chapter 1](#what-goes-wrong), its first recorded run broke on a single call. The open model, Qwen3-4B replayed from its recording, read the right file, misread the issue as asking it to drop the zeros, and then wrote each change as a whole file, in Python triple quotes, inside the JSON of a `finish` call. Triple quotes are not valid inside a JSON string, so those arguments never parsed. No tool ran, and the run ended at its step cap.

This chapter compares two tool sets. **Tool set v1** is the seven tools the task-set recording was made with: `list_files`, `read_file`, `run_tests`, `write_file`, `edit_file`, `ask_user` and `finish`. **Tool set v2** has the same seven tools as tool set v1, with the same sentences and the same system prompt, and three changes: strict argument models, the error type named in each refusal, and nearest-line errors for a failed edit.

The misreading is the model's own, and no tool design fixes it. The malformed calls have two parts. The call had a shape the harness could not read, and the change travelled inside a string the model had to escape correctly. This chapter deals with both. Each tool gets an argument schema that the harness checks before it runs, and a refusal goes back to the model as text it can act on. In tool set v1 the change also leaves `finish`: the model edits its copy with `edit_file` and `write_file`, and `finish` carries only a summary. Small edits bring their own quoting trouble, which the last section takes up.

## A schema says what is allowed {#schema-says}

A model writes a tool call from what it has been told about the tool, and the harness can refuse a bad call only by checking it against the same description. Each tool in the set has three parts: a name, one sentence of description, and an argument model, a small pydantic class that lists the fields the tool takes. The harness sends each tool's schema with the request, and the schema is built from that class, so the text the model reads and the check the harness runs come from one place.

That single place matters because a schema holds more than field names. Think of a tool's schema as the form the model fills in before it makes a call. Each line of the form names a field, says what kind of answer it wants, and may say how large an answer may be. A form can guide the person filling it in, but it cannot stop a wrong answer from being written. That is where the form stops being useful as a guard, and the harness has to do the checking that the form cannot.

Pydantic writes each field's type, its description, its default and its bounds into the schema. The case's tools take only paths and strings, so this section uses a different read, one with a line limit that no tool in the set uses. It is a teaching model, chosen to show what a bound looks like. Printing its schema is the quickest way to see what the model is told, and the bounds and the default are the lines to read.

[Example: schema-from-model](../examples/schema-from-model.py)

Read the output as the model reads it. The only required argument is `{{out:schema-from-model:required}}`. `max_lines` takes values from {{out:schema-from-model:max_lines minimum}} to {{out:schema-from-model:max_lines maximum}}.

Its default is the other half of the field. When the model leaves `max_lines` out, the value is {{out:schema-from-model:max_lines default}}. Those bounds sit in the schema the model reads, not only in the code that checks them, and the field's own description says the same in words: "{{out:schema-from-model:max_lines description}}"

A default in a schema is a note, not a rule. The [JSON Schema validation specification](https://json-schema.org/draft/2020-12/json-schema-validation) treats `default` as an annotation: it supplies a value, and it checks nothing. Whether a harness fills the default in is the harness's choice, and the schema alone does not make it happen.

The other half of what the model reads is each tool's sentence. Those sentences sit beside their schemas in every request, so the example below prints them. Two lines are worth checking: the one that says which chapter 1 tools share a sentence with this set, and the one that says `finish` does not.

[Example: tool-descriptions](../examples/tool-descriptions.py)

Tool set v1 has {{out:tool-descriptions:v1 tools}} tools, each with one sentence. The printout confirms that chapter 1's tools keep their sentences in this set, and they do for {{out:tool-descriptions:ch1 tools with the same sentence in v1}}. Its `finish` is the one that changed, because its job did. A tool's sentence says what the tool is for. It cannot carry a rule the harness does not check.

**Working rule:** Write each bound, type and default in the argument model, where the harness checks it, and give each field a description the model can read. Keep the tool's sentence to what the tool is for. A rule that lives only in the sentence is a hint the harness will never enforce.

## Lax by default, strict on purpose {#lax-or-strict}

A model asked for a number may write `"50"`, and a flag may arrive as `true`. The harness has to decide whether to take those values as meant, and pydantic answers by mode. In pydantic's default, lax mode, a value is converted when the conversion is clear and refused when it is not. In strict mode, a value must already have the declared type. The tool set v1 argument models use the default, and tool set v2's copies of them are strict.

The schema is a hint, not a guarantee. OpenAI's [function-calling guide](https://developers.openai.com/api/docs/guides/function-calling) describes a setting also called `strict`, which constrains what the model generates: with it on, calls follow the schema reliably, and without it they are best effort. Pydantic's strict mode is a different mechanism. It checks a call after it arrives and does not constrain generation. This harness does not constrain what the model writes while it writes it, so every call is checked after it arrives, whatever the schema said.

A model that writes `"50"` for a line limit most likely means fifty, so refusing it outright would waste a step on a call that was nearly right. A model that sends `true` for the same field has meant something else entirely, and converting it to a number would hide that. Neither answer is right for every field, so the mode has to be chosen for each argument model that holds those fields. This chapter sets it on each model and not on each field.

The next example sends the same values through both modes. Compare what each mode does with each value.

[Example: lax-and-strict](../examples/lax-and-strict.py)

What strict mode changes is the conversions, and nothing else the example shows. A value of the declared type passes in both modes. The string `"50"` is accepted in lax mode and refused in strict mode, with {{out:lax-and-strict:strict, max_lines str 50}}. A flag is treated the same way: `True` is accepted in lax mode, and strict mode refuses it with {{out:lax-and-strict:strict, max_lines bool True}}. Lax mode also takes `2.0` for an int, because nothing is lost in the conversion. It refuses `2.5`, because the fraction would be lost, and its refusal reads {{out:lax-and-strict:lax, max_lines float 2.5}}.

The tool set v2 copies are written as subclasses of the tool set v1 classes. Each one keeps every field of its parent and changes only the mode, so tool set v1 keeps the classes it had and prints what it printed before. Adding a setting beside the old one, rather than in place of it, lets a tool set change without changing what an earlier run printed. The mode does not appear in the schema the model reads. The example shows that the schemas of the two tool sets differ only in each class's title, `StrictPathArg` where tool set v1 has `PathArg`. The class name is the one thing a model could see of strict mode.

Strict mode is not free of cost. It turns a usable call into a refusal, and the model then has to try again. What it buys is that a count the tool receives is a count, and that a flag is never read as a number by accident. Whether that trade is worth it depends on the field, and on the case's tools it changes nothing. Every argument of the case's tools is a string. On a string field, lax and strict refuse the same values. The last lines of the printout try a string, a number, a float, a flag, nothing, a list and an object, and the number, for one, is refused in both modes with {{out:lax-and-strict:strict, path int 3}}. So tool set v2's strict setting changes no refusal that a JSON call can cause on these tools. It guards a field that a later tool might add as a number. Only the bounded read converts, and no tool uses it.

**Working rule:** Use lax mode where a conversion is what the model meant, and strict mode where a quiet conversion would change what the tool does. Test each model with a value of the wrong type before you rely on it, and read the error type the refusal names, since that is what the model will see.

## Errors the model can read {#errors-readable}

A refusal helps only when the model can read what was wrong with its call. A run that stops at the first bad call teaches the model nothing, and a harness that drops a bad call silently leaves the model guessing at its next step. So each refusal goes back as the text of a tool result, the same kind of text as any other result, which the model reads on its next step.

Bad calls fail at different points, and the harness has to check them in order. A refusal that arrives during a step is one more tool result in the transcript. The run goes on, the model's next reply can react to it, and the step cap still applies. So a bad call costs the model a step, and the refusal decides whether that step was spent usefully.

Each of the bad calls in this example is wrong in a different way. They go through tool set v2 and then through tool set v1, and the printout shows what each set hands back:

[Example: bad-arguments-handed-back](../examples/bad-arguments-handed-back.py)

The first failure happens before any schema is consulted. The call whose JSON is cut off never reaches a tool, because the reply parser cannot read it. Its reason is `not JSON`, followed by the JSON parser's own message. That message comes from the Python standard library, not from pydantic, and the call has no field to name, since its arguments never parsed.

The other calls parse and reach the schema, and each one gets its own refusal. A call with no arguments for `read_file` is refused for `path`, with the error type `missing`. A key the tool does not take, `lines` in this case, is refused as `extra_forbidden`, even though the rest of the call is sound. A `path` given as a number is refused as `string_type`. Every refusal names the field, the error type and the message, so the model's next call can change the one thing that was wrong. The field is named in the schema's own words, `path` and not the name of a Python class, because those are the words the model is working with.

Tool set v1 uses the same fields without strict mode, so for calls 2 to 4 it refuses the same calls, with the same fields and messages, as the tool set v1 lines in the printout show. Its text leaves out the error type, and naming that type is the one addition tool set v2 makes to these refusals. Compare the missing `path` in call 2. Tool set v1 says `{{out:bad-arguments-handed-back:call 2, read_file, v1}}`, and tool set v2 says `{{out:bad-arguments-handed-back:call 2, read_file, v2}}`.

Each of these refusals asks for a different repair, and the text is what tells the model which one. A missing field asks for the field to be added. An extra key asks for it to be removed, and a wrong type asks for the value to be written the way the schema says. A model that gets only "invalid arguments" has to guess which of those three it owes, and a guess spends a step. Naming the field and the error type turns the guess into a single edit to the call.

**Working rule:** Return each refusal as a tool result that names the field, the error type and the message. Never end the run on a bad call, except through the stop rules in [chapter 2](#repeated-calls), when they are on and the same bad call keeps coming back. A call the parser cannot read gets the parser's reason as its refusal, and no tool runs on it.

## One name per tool {#one-name}

The name is the first thing a call gives the harness, and the harness can check it before it reads any argument. A model that invents a tool, or remembers one wrongly, makes a call with nothing behind it, and the harness has to say so in terms the model can use.

The last call in the example from the [previous section](#errors-readable) asks for `read_files`, a tool the set does not have, with a `path` that would suit `read_file`. Its refusal lists the names the set does have, so the model's next call can use one of them. The tool set v2 refusal opens with `invalid arguments`, because the harness checks the name as a field of the call, and the field is called `name`. The harness builds a `Literal` type from the names of the tools in the set and checks the name against it. A wrong name fails as `literal_error`, and the message gives the allowed names. Tool set v1 gives a shorter text for the same call: `{{out:bad-arguments-handed-back:call 5, read_files, v1}}`. It says the tool is unknown, and nothing about which tools are.

The name sits outside each tool's parameters, so no parameters schema prevents a wrong name. The check happens when the harness looks the name up, which is why it belongs in the harness and not only in the prompt.

The harness does not guess, and that difference matters. A name close to a real tool, such as `read_files` for `read_file`, is still refused, because the harness dispatches on exact names and a guess would run a tool the model did not ask for. The refusal does the helping: it lists what exists, and the model chooses again.

The name matters most for the stop tool. The loop ends a run when a `finish` or `ask_user` call runs and its result carries the end flag. A misspelled stop tool carries no such flag. It is refused like any other unknown name, and the run goes on until the step cap or a stop rule ends it. The same exact-name check that refuses `read_files` is what makes `finish` mean `finish`. A model that keeps asking for a tool the set lacks is the kind of run the [stop rules in chapter 2](#repeated-calls) are for.

**Working rule:** Take the allowed names from the tools the loop actually runs, never from a list kept beside them, and put them in every refusal for an unknown name. A name the set lacks gets a refusal, and the prompt does not promise it. Accept an alias only through an explicit alias map that the harness keeps, never by a guess.

## Edit errors that name the nearest lines {#edit-errors}

An edit names the text it replaces and the text that replaces it. The tool set v1 `edit_file` tool changes the one place where `old` appears in the file, and it refuses the call when `old` is missing or appears more than once. An edit can therefore fail over a few quoted characters. A model that copies code from its own reading of a file can get those quotes wrong, and then the edit is refused.

The first version of the change, in chapter 1, put the whole file inside one JSON string, so every quote and newline in the file had to be escaped in the model's reply. An edit is smaller. It copies only the lines that change, so there are fewer characters to get wrong. The escaping problem does not go away, though, because the copy still has to match the file exactly.

The task-set recording shows the copy going wrong. It holds the replies of the same open model, Qwen3-4B-Instruct-2507, over twenty tasks, run with tool set v1, a step cap of {{out:stop-rules-over-task-set:task set step cap}} and temperature 0; [chapter 1](#replayed-run) explains the model's setup. In T-01's third reply, the model copied a few lines into `old` and dropped the quotes around two f-strings and the closing quote of `separator = "."`. The file has those quotes. The stored `old` text is printed first, then that one reply is replayed through both tool sets, so the difference shows:

[Example: edit-error-nearest-lines](../examples/edit-error-nearest-lines.py)

The tool set v1 text says only that the old text is not in the file, and it names the file. The tool set v2 text does more. It gives the nearest lines of the file, numbered as the file numbers them and with their quotes as they are, and it ends by saying what to do next: copy `old` from those lines, quotes included, and call again. The refusal carries a window of lines and not the whole file. A whole file would answer the model's question at a cost of many tokens, and every tool result counts against the same context that holds the task, as [chapter 5](#where-tokens-go) counts them. The lines are found by similarity. The harness slides a window of as many lines as `old` down the file, keeps the window that matches best, and breaks a tie toward the earlier window, so the answer is the same on every run. Here the best window holds the f-string line the model was copying, with its quotes, and the example asserts that the line appears in the error.

If the model repeats the same failing edit, the stop rules in [chapter 2](#repeated-calls) end the run, provided they are switched on. They are off by default, and the task-set recording did not switch them on. The nearest lines are meant to make such a repeat less likely. The tool set v1 text leaves the model a second step to spend: it has to call `read_file` to see the lines it should have copied, and the next reply may still copy them wrongly. The tool set v2 text puts those lines in the refusal itself, so the model can try again at once. The printout shows the text the harness returns, not whether the next edit succeeds. That takes a run, and [chapter 10](#v1-v2) counts the runs. This chapter reports no count of either kind.

**Working rule:** When an edit's text is not in the file, return the file's nearest lines with their numbers, and say what to do next. Do not return only that the text is missing, since that leaves the model to guess which quote is wrong. A file short enough to return whole can be returned whole, numbered, in its place.

## Decisions in this chapter {#decisions}

The schemas and the error texts are part of the model's input. Changing a sentence, a field or an error text changes the request, and the replays in this book compare each request with the recorded one and refuse to answer when they differ. A tool set therefore changes together with its recording, and never in place.

This chapter's promises carry forward. [Model adapters](#model-protocol) uses these same schemas for every adapter. [Context budgets](#where-tokens-go) counts each refusal as a tool result, like any other. [Testing the agent](#v1-v2) compares two harness versions as counts. Their tool sets are these two; the version on tool set v2 also adds the other changes that chapter 10 lists.

The decisions are these:

- Every argument model in the tool set forbids keys it does not declare, so an invented key is refused and not ignored.
- The tool set v1 argument models keep pydantic's lax default, since the recorded task-set runs used it. The tool set v2 copies are strict. On the case's tools they refuse the same JSON values as the lax copies do, so the strictness changes no refusal there.
- The case's tools have no field that is not a string. The bounded read is the only place the mode is shown, and no tool uses it.
- A refusal names the field, its error type and its message. Tool set v1 omits the error type.
- The allowed tool names come from the tools the loop runs, and an unknown name is refused with them.
- In tool set v1, `finish` carries a summary, and the changes are made with `edit_file` and `write_file` in the copy.
- An edit whose text is missing returns the nearest lines of the file, numbered. That is a tool set v2 change.
- The error texts this chapter discusses are printed by its examples, so a change to one shows in the printout before it shows in a run. The other refusals in the tool code, such as a path outside the case, are not printed here.
