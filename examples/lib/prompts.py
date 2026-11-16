"""The prompts and tool descriptions the harness sends. Every string a model sees is in this module.

Two tool sets are defined. Chapter 1 uses ``CH1``: three tools, and ``finish(path, text)`` writes a file and
ends the run. The task-set recording uses ``V1``: seven tools; ``write_file`` makes a new file only, ``edit_file``
changes an existing one, and ``finish(summary)`` only ends the run. The texts are fixed before a recording runs;
a recording's manifest holds the hash from ``prompt_sha256``, so a changed prompt shows up as a changed hash.

Nothing here names a hidden check, an expected output, or the value a test compares.
"""
from __future__ import annotations

import hashlib
import json

SYSTEM_CH1 = (
    "You are a maintenance agent for the unitcraft library. You have three tools: read_file(path), run_tests(), "
    "and finish(path, text). Call one tool per reply. To change code, call finish with the whole new text of one "
    "file; the harness applies it to a copy and runs the tests. Reply with a tool call only."
)

SYSTEM_V1 = (
    "You are a maintenance agent for the unitcraft library. You have seven tools, and you call one per reply:\n"
    "list_files() lists the files in your copy.\n"
    "read_file(path) returns the text of one file.\n"
    "run_tests() runs the visible test suite on your copy and returns the counts.\n"
    "write_file(path, text) creates a new file in your copy; it is refused when the file exists.\n"
    "edit_file(path, old, new) replaces the one occurrence of old with new in an existing file.\n"
    "ask_user(question) ends the run to ask the person a question, with the reason you need the answer.\n"
    "finish(summary) ends the run with a summary of what you changed and why.\n"
    "When the change is done, call finish with a summary. If a step needs a person's approval, or the task is "
    "ambiguous, out of scope or impossible, call ask_user. Reply with a tool call only."
)

# One plain sentence per tool. Chapter 1 and the v1 set use the same sentences where a tool is shared.
DESC_LIST_FILES = "List the files in the case, by their case-relative paths."
DESC_READ_FILE = "Read one file in the case, given by its case-relative path."
DESC_RUN_TESTS = "Run the visible test suite on your copy and return the counts of passed and failed tests."
DESC_WRITE_FILE = "Create a new file in your copy with this text; it is refused when the file already exists."
DESC_EDIT_FILE = "Replace the one occurrence of old text with new text in a file in your copy."
DESC_ASK_USER = "Ask the person a question and end the run; use it when the task needs their decision."
DESC_FINISH = "End the run with a summary of what you changed and why."
DESC_FINISH_PATH = (
    "Write the whole new text of one file into your copy, run the tests, and end the run."
)

PARAM_PATH = "A file path relative to the case root, with / as the separator."
PARAM_TEXT = "The whole new text of the file."
PARAM_OLD = "The exact text to replace; it must occur exactly once in the file, so include enough lines."
PARAM_NEW = "The text to put in its place."
PARAM_QUESTION = "The question for the person, with the reason you need the answer."
PARAM_SUMMARY = "What you changed and why, in a few sentences."


def prompt_sha256(system: str, descriptions: list[str]) -> str:
    """Return the sha256 of a tool set's system prompt and tool descriptions, joined as JSON."""
    text = json.dumps({"system": system, "tools": descriptions}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
