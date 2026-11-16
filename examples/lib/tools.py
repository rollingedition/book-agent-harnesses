"""The tools the agent may call, the path rules they follow, and the test runner behind ``run_tests``.

Tools run in this process, on the run's scratch copy. Every refusal is returned to the model as text that starts
with ``error:``; nothing is raised into the loop. The test runner runs pytest through ``lib.sandbox``'s limits
with a harness-owned config (chapter 7), but the tests still run code the model wrote, so only a container confines
them. The path rules here are a defence in depth; no tool set offers the model a command tool.

Teaching code: the argv list is built here and never passed to a shell, and the environment is an allowlist.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from .case import IGNORED
from .prompts import (
    DESC_ASK_USER, DESC_FINISH, DESC_FINISH_PATH, DESC_LIST_FILES, DESC_READ_FILE, DESC_RUN_TESTS,
    DESC_EDIT_FILE, DESC_WRITE_FILE, PARAM_NEW, PARAM_OLD, PARAM_PATH, PARAM_QUESTION, PARAM_SUMMARY, PARAM_TEXT,
    SYSTEM_CH1, SYSTEM_V1,
)

TEST_TIMEOUT = 120  # seconds; a run that takes longer is stopped, its group killed
ENV_KEEP = ("PATH", "LANG", "LC_ALL", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "TOKENIZERS_PARALLELISM")


class ToolError(Exception):
    """A refusal, carried back to the model as its text (it starts with ``error:``)."""


class Workspace:
    """A run's scratch copy, and the only place the tools may read or write."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._real = root.resolve()

    def locate(self, rel: str, *, write: bool = False) -> Path:
        """Resolve a case-relative path inside the copy, or raise ``ToolError``.

        Refused: absolute paths, ``..`` parts, NUL bytes, non-NFC text, and any path that resolves (through a
        symlink) outside the copy. A write to ``.github/`` is refused too.
        """
        if not isinstance(rel, str) or not rel or "\x00" in rel or "\\" in rel:
            raise ToolError(f"error: path outside the case: {rel}")
        if unicodedata.normalize("NFC", rel) != rel:
            raise ToolError(f"error: path is not in NFC form: {rel}")
        parts = PurePosixPath(rel)
        if parts.is_absolute() or ".." in parts.parts:
            raise ToolError(f"error: path outside the case: {rel}")
        target = (self.root / parts).resolve()
        if not target.is_relative_to(self._real):
            raise ToolError(f"error: path outside the case: {rel}")
        inner = target.relative_to(self._real).parts
        if write and inner and inner[0] == ".github":
            raise ToolError(f"error: .github/ is not writable: {rel}")
        return target

    def list_files(self) -> list[str]:
        """Every file in the copy, as sorted case-relative paths (caches left out)."""
        found = []
        for path in sorted(self.root.rglob("*")):
            rel = path.relative_to(self.root)
            if path.is_file() and not any(part in IGNORED for part in rel.parts):
                found.append(rel.as_posix())
        return sorted(found)

    def run_tests(self) -> str:
        """Run the visible suite on the copy and return counts, with the failing tests' lines."""
        with tempfile.TemporaryDirectory(prefix="pytest-config-") as folder:
            result = run_pytest(self.root, ["-rfE"], config_dir=Path(folder))
        return summarize_pytest(result, self.root)


@dataclass(frozen=True)
class CommandResult:
    code: int | None
    out: str
    timed_out: bool


def clean_env(home: Path) -> dict[str, str]:
    """The environment a test run gets: an allowlist from this process, plus fixed values. No API keys."""
    env = {name: os.environ[name] for name in ENV_KEEP if name in os.environ}
    env.update(HOME=str(home), PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    return env


def run_command(argv: list[str], *, cwd: Path, timeout: float) -> CommandResult:
    """Run an argv list (never a shell string) through the sandbox's runner: its limits, its time limit, and the
    process group killed on every path. There is one runner; this name is kept for callers that expect it.
    """
    from .sandbox import run_sandboxed  # sandbox imports this module, so its import waits until this one has loaded

    if not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError("argv must be a non-empty list of strings")
    result = run_sandboxed(argv, cwd=cwd, timeout=timeout)
    return CommandResult(result.code, result.out, result.timed_out)


def run_pytest(root: Path, args: list[str], *, config_dir: Path) -> CommandResult:
    """Run pytest on the folder ``root`` with the harness's own configuration, so no file the agent wrote takes effect.

    ``-I`` keeps the working folder off ``sys.path`` and ignores ``PYTHON*`` variables, so a ``pytest.py`` or other
    module in the folder cannot stand in for pytest or a plugin. ``-c`` names an ini file written into
    ``config_dir``, outside ``root``, so the folder's ``pytest.ini``, ``tox.ini``, ``setup.cfg`` and ``pyproject.toml``
    are not read. ``--noconftest`` stops every ``conftest.py``. ``--rootdir`` pins the node IDs. The harness's ini keeps
    the case's own ``testpaths`` and adds the folder to the import path, so ``unitcraft`` imports as before.
    """
    ini = config_dir / "harness.ini"
    ini.write_text(f"[pytest]\ntestpaths = tests\npythonpath = {root}\n", encoding="utf-8")
    argv = [sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--noconftest",
            "-c", str(ini), "--rootdir", str(root), *args]
    return run_command(argv, cwd=root, timeout=TEST_TIMEOUT)


SUMMARY = re.compile(r"^=* ?((?:\d+ \w+(?:, )?)+) in \d+(?:\.\d+)?s")
COUNT = re.compile(r"(\d+) (failed|passed|errors?|skipped)")
ORDER = ("failed", "passed", "error", "skipped")


def summarize_pytest(result: CommandResult, root: Path) -> str:
    """Turn a pytest run into counts and the failing lines, sorted. Pytest's own summary line is never shown.

    The elapsed time on that line changes between runs (plan section 12, row 7), so only its counts are kept.
    Exit code 5 means no tests were collected (row 6).
    """
    if result.timed_out:
        return "error: the test run was stopped at its time limit"
    if result.code == 5:
        return "no tests ran"
    lines = [redact(line, root) for line in result.out.splitlines()]
    summary = next((m for m in (SUMMARY.match(line) for line in reversed(lines)) if m), None)
    if summary is None:
        return f"error: the test run did not finish (exit code {result.code})"
    counts = {}
    for n, kind in COUNT.findall(summary.group(1)):
        counts["error" if kind.startswith("error") else kind] = int(n)
    shown = [f"{counts[k]} {k}" for k in ORDER if counts.get(k)]
    failing = sorted(line for line in lines if line.startswith(("FAILED ", "ERROR ")))
    return "\n".join([", ".join(shown) or "no tests ran", *failing])


def redact(text: str, root: Path) -> str:
    """Replace the copy's folder with ``<case>`` so no absolute path reaches the output."""
    for form in sorted({str(root), str(root.resolve())}, key=len, reverse=True):
        text = text.replace(form, "<case>")
    return text


# ---- tool arguments (pydantic: the schema and the checks) -----------------------------------------------------

class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PathArg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(description=PARAM_PATH)


class WriteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(description=PARAM_PATH)
    text: str = Field(description=PARAM_TEXT)


class EditArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(description=PARAM_PATH)
    old: str = Field(description=PARAM_OLD)
    new: str = Field(description=PARAM_NEW)


class QuestionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(description=PARAM_QUESTION)


class SummaryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(description=PARAM_SUMMARY)


# Chapter 3's v2 argument models: the same fields as above, with strict checking. Pydantic's default is lax:
# it turns "50" into 50 for an int. strict=True refuses that; extra="forbid" refuses keys the model does not have.
class StrictNoArgs(NoArgs):
    model_config = ConfigDict(strict=True, extra="forbid")


class StrictPathArg(PathArg):
    model_config = ConfigDict(strict=True, extra="forbid")


class StrictWriteArgs(WriteArgs):
    model_config = ConfigDict(strict=True, extra="forbid")


class StrictEditArgs(EditArgs):
    model_config = ConfigDict(strict=True, extra="forbid")


class StrictQuestionArgs(QuestionArgs):
    model_config = ConfigDict(strict=True, extra="forbid")


class StrictSummaryArgs(SummaryArgs):
    model_config = ConfigDict(strict=True, extra="forbid")


# Chapter 3's teaching model for a bounded read. No tool in a tool set uses it, so the v1 and v2 schemas do not change.
PARAM_MAX_LINES = "The most lines to return, from 1 to 1000; the default is 200."


class LinesArgs(BaseModel):
    """A read with a line limit, in pydantic's default (lax) mode: the schema carries the bounds and the default."""
    path: str = Field(description=PARAM_PATH)
    max_lines: int = Field(default=200, ge=1, le=1000, description=PARAM_MAX_LINES)


class StrictLinesArgs(LinesArgs):
    """The same fields in strict mode, which refuses a string or a bool where an int is due."""
    model_config = ConfigDict(strict=True, extra="forbid")


# ---- tools ----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolResult:
    """What a tool returns: the text the model reads, a short line for the trace, and how it ends the run."""

    text: str
    brief: str = ""
    end: str | None = None  # "finish" or "ask_user" when the call ends the run
    question: str = ""
    summary: str = ""


Runner = Callable[[Workspace, BaseModel], ToolResult]


@dataclass(frozen=True)
class Tool:
    """A tool's name, its one-sentence description, its argument model and the function that runs it."""

    name: str
    description: str
    args: type[BaseModel]
    run: Runner

    def schema(self) -> dict:
        """The function schema the model's chat template receives."""
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                  "parameters": self.args.model_json_schema()}}


def _list_files(ws: Workspace, args: NoArgs) -> ToolResult:
    files = ws.list_files()
    return ToolResult("\n".join(files), brief=f"{len(files)} files")


def _read_file(ws: Workspace, args: PathArg) -> ToolResult:
    target = ws.locate(args.path)
    if not target.is_file():
        raise ToolError(f"error: no such file: {args.path}")
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ToolError(f"error: not a text file: {args.path}") from None
    count = len(text.splitlines())
    return ToolResult(text, brief=f"{count} line" if count == 1 else f"{count} lines")


def _run_tests(ws: Workspace, args: NoArgs) -> ToolResult:
    text = ws.run_tests()
    return ToolResult(text, brief=text.splitlines()[0])


def _write(ws: Workspace, args: WriteArgs, *, new_only: bool) -> ToolResult:
    target = ws.locate(args.path, write=True)
    if target.is_dir():
        raise ToolError(f"error: is a folder: {args.path}")
    if new_only and target.exists():
        raise ToolError(f"error: {args.path} exists; use edit_file")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(args.text, encoding="utf-8")
    return ToolResult(f"wrote {args.path}", brief=f"wrote {args.path}")


def _write_file(ws: Workspace, args: WriteArgs) -> ToolResult:
    """The v1 writer: makes a new file only. An existing file is changed with ``edit_file``."""
    return _write(ws, args, new_only=True)


def nearest_lines(text: str, old: str) -> tuple[int, list[str]]:
    """The run of lines in ``text`` most like ``old``: its first line number (from 1) and the lines.

    The run has as many lines as ``old``. Ties go to the earlier run, so the answer is the same on every run.
    """
    lines = text.splitlines()
    size = max(1, len(old.splitlines()))
    wanted = "\n".join(old.splitlines())
    best, best_ratio = 0, -1.0
    for start in range(max(1, len(lines) - size + 1)):
        window = "\n".join(lines[start:start + size])
        ratio = SequenceMatcher(None, wanted, window, autojunk=False).ratio()
        if ratio > best_ratio:
            best, best_ratio = start, ratio
    return best + 1, lines[best:best + size]


def _edit(ws: Workspace, args: EditArgs, *, nearest: bool) -> ToolResult:
    """Replace the one occurrence of ``old`` in an existing file. Refused as text when it is missing or repeated.

    With ``nearest``, a missing ``old`` is refused with the file's nearest lines, numbered as in the file.
    """
    target = ws.locate(args.path, write=True)
    if not target.is_file():
        raise ToolError(f"error: no such file: {args.path}")
    if not args.old:
        raise ToolError("error: old text is empty; give the lines to replace")
    text = target.read_text(encoding="utf-8")
    count = text.count(args.old)
    if count == 0 and nearest:
        first, lines = nearest_lines(text, args.old)
        shown = "\n".join(f"{first + i:>5} | {line}" for i, line in enumerate(lines))
        raise ToolError(
            f"error: old text not found in {args.path}. The nearest lines of the file, numbered as in the file:\n"
            f"{shown}\nCopy old from those lines exactly, quotes included, and call edit_file again."
        )
    if count == 0:
        raise ToolError(f"error: old text not found in {args.path}")
    if count > 1:
        raise ToolError(f"error: old text occurs {count} times in {args.path}; include more lines")
    target.write_text(text.replace(args.old, args.new, 1), encoding="utf-8")
    return ToolResult(f"edited {args.path}", brief=f"edited {args.path}")


def _edit_file(ws: Workspace, args: EditArgs) -> ToolResult:
    return _edit(ws, args, nearest=False)


def _edit_file_nearest(ws: Workspace, args: EditArgs) -> ToolResult:
    """The v2 edit: the same change, and a missing ``old`` is refused with the nearest lines of the file."""
    return _edit(ws, args, nearest=True)


def _ask_user(ws: Workspace, args: QuestionArgs) -> ToolResult:
    return ToolResult("handed to the person", brief="ask_user", end="ask_user", question=args.question)


def _finish(ws: Workspace, args: SummaryArgs) -> ToolResult:
    return ToolResult("run ended", brief="finish", end="finish", summary=args.summary)


def _finish_path(ws: Workspace, args: WriteArgs) -> ToolResult:
    """Chapter 1's stop tool: write one file, run the tests, end the run. A refused write does not end it."""
    _write(ws, args, new_only=False)  # chapter 1 replaces a whole file; its writer does not refuse an existing one
    counts = ws.run_tests()
    return ToolResult(counts, brief=counts.splitlines()[0], end="finish", summary=args.path)


LIST_FILES = Tool("list_files", DESC_LIST_FILES, NoArgs, _list_files)
READ_FILE = Tool("read_file", DESC_READ_FILE, PathArg, _read_file)
RUN_TESTS = Tool("run_tests", DESC_RUN_TESTS, NoArgs, _run_tests)
WRITE_FILE = Tool("write_file", DESC_WRITE_FILE, WriteArgs, _write_file)
EDIT_FILE = Tool("edit_file", DESC_EDIT_FILE, EditArgs, _edit_file)
ASK_USER = Tool("ask_user", DESC_ASK_USER, QuestionArgs, _ask_user)
FINISH = Tool("finish", DESC_FINISH, SummaryArgs, _finish)
FINISH_PATH = Tool("finish", DESC_FINISH_PATH, WriteArgs, _finish_path)


S_LIST_FILES = Tool("list_files", DESC_LIST_FILES, StrictNoArgs, _list_files)
S_READ_FILE = Tool("read_file", DESC_READ_FILE, StrictPathArg, _read_file)
S_RUN_TESTS = Tool("run_tests", DESC_RUN_TESTS, StrictNoArgs, _run_tests)
S_WRITE_FILE = Tool("write_file", DESC_WRITE_FILE, StrictWriteArgs, _write_file)
S_EDIT_FILE = Tool("edit_file", DESC_EDIT_FILE, StrictEditArgs, _edit_file_nearest)
S_ASK_USER = Tool("ask_user", DESC_ASK_USER, StrictQuestionArgs, _ask_user)
S_FINISH = Tool("finish", DESC_FINISH, StrictSummaryArgs, _finish)


@dataclass(frozen=True)
class ToolSet:
    """A named set of tools, the system prompt that goes with it, and the step cap for a run.

    ``typed_errors`` adds each problem's pydantic error type to a refused call's text (``path (missing)``). It is
    off for v1 and ch1, whose text stays as it was.
    """

    name: str
    system: str
    step_cap: int
    tools: tuple[Tool, ...]
    typed_errors: bool = False

    def get(self, name: str) -> Tool | None:
        return next((t for t in self.tools if t.name == name), None)

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self.tools]

    def descriptions(self) -> list[str]:
        return [t.description for t in self.tools]

    def call(self, ws: Workspace, name: str, arguments: dict) -> ToolResult:
        """Run one call. Unknown names and bad arguments come back as ``error:`` text, never as exceptions."""
        tool = self.get(name)
        if tool is None and self.typed_errors:
            # The name is a Literal of this set's tools, so a wrong name fails as a literal_error that lists them.
            names = tuple(t.name for t in self.tools)
            try:
                create_model("Call", name=(Literal[names], ...)).model_validate({"name": name})
            except ValidationError as exc:
                text = f"error: invalid arguments: {_problem(exc.errors()[0], True)}"
                return ToolResult(text, brief="error: invalid arguments")
        if tool is None:
            return ToolResult(f"error: unknown tool: {name}", brief="error: unknown tool")
        try:
            args = tool.args.model_validate(arguments)
        except ValidationError as exc:
            problems = "; ".join(_problem(e, self.typed_errors) for e in exc.errors())
            return ToolResult(f"error: invalid arguments: {problems}", brief="error: invalid arguments")
        try:
            return tool.run(ws, args)
        except ToolError as exc:
            text = str(exc)
            return ToolResult(text, brief=text[:80])


def _problem(error: dict, typed: bool) -> str:
    """One validation error as the model reads it: the field, its error type if asked for, and the message."""
    where = ".".join(str(part) for part in error["loc"])
    kind = f" ({error['type']})" if typed else ""
    return f"{where}{kind}: {error['msg']}"


V1 = ToolSet("v1", SYSTEM_V1, 16,
             (LIST_FILES, READ_FILE, RUN_TESTS, WRITE_FILE, EDIT_FILE, ASK_USER, FINISH))
CH1 = ToolSet("ch1", SYSTEM_CH1, 8, (READ_FILE, RUN_TESTS, FINISH_PATH))
# Chapter 3's v2: the v1 tools with strict arguments, typed errors, and nearest-line edit errors. Same system prompt
# and descriptions as v1, so only the schemas and the error texts differ.
V2 = ToolSet("v2", SYSTEM_V1, 16,
             (S_LIST_FILES, S_READ_FILE, S_RUN_TESTS, S_WRITE_FILE, S_EDIT_FILE, S_ASK_USER, S_FINISH),
             typed_errors=True)
