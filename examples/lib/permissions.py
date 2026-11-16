"""The approval gate: the agent's copy changes freely, and a change to the case library waits for a person's yes.

Teaching code. The primary defences are structural: the agent's tools work on its own scratch copy (``lib/tools.py``),
and the case library changes only when ``apply`` runs after a yes. The checks here are a second layer. A tool that is
not in ``TOOL_CLASS`` is refused and never run. A diff that touches a test or ``.github/`` is refused whatever the
person says. A yes binds to the exact bytes of every changed file. ``apply`` writes all of a proposal or none of it.
A guard compares the library's bytes around every tool call and ends the run as ``library_changed`` if they moved.
``run_tests`` runs code the model wrote, so until chapter 7's sandbox runs the tests it is the open side: the guard
reports a write the tests make to the library, but it does not stop the write. Nothing here reads the clock or draws
random numbers.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
import shutil
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, Mapping

from pydantic import BaseModel

from .case import CASE, DATA, IGNORED, load_tasks, scratch_copy
from .loop import Run, run_task
from .models import ReplayModel, ScriptedModel
from .tools import V1, Tool, ToolResult, ToolSet, Workspace
from .trace import IdCounter

READ, CHANGE, PROPOSE, NEVER = "read", "change", "propose", "never"
TOOL_CLASS = {"list_files": READ, "read_file": READ, "run_tests": READ, "ask_user": READ,
              "write_file": CHANGE, "edit_file": CHANGE, "finish": PROPOSE}
GITHUB = ".github"
TESTS = "tests/"


def classify(name: str, classes: Mapping[str, str] | None = None) -> str:
    """The class of a tool, from ``TOOL_CLASS`` or, when given, the harness's own ``classes``. A name in neither is never
    run: the gate refuses the call."""
    if classes and name in classes:
        return classes[name]
    return TOOL_CLASS.get(name, NEVER)


@dataclass(frozen=True)
class Change:
    """One file whose bytes differ between the library and the copy. ``None`` means the file is absent on that side."""

    path: str
    old: bytes | None
    new: bytes | None


def _files(root: Path) -> dict[str, bytes]:
    found = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and not any(part in IGNORED for part in rel.parts):
            found[rel.as_posix()] = path.read_bytes()
    return found


def pending(library: Path, scratch: Path) -> list[Change]:
    """Every file whose bytes differ between the library and the copy, sorted by path."""
    before, after = _files(library), _files(scratch)
    return [Change(p, before.get(p), after.get(p)) for p in sorted(set(before) | set(after))
            if before.get(p) != after.get(p)]


def _escape(text: str) -> str:
    """The text with every character a terminal could act on, or that prints as nothing, written out. A newline and a
    tab stay. A backslash is doubled, so an escape on the screen can only be an escape in the file."""
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch in "\n\t" or ch.isprintable():
            out.append(ch)
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 0x100:
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(f"\\u{ord(ch):04x}")
    return "".join(out)


def _hidden(text: str) -> bool:
    """True when the text holds a character that ``_escape`` would write out (not counting backslashes)."""
    return any(not (ch.isprintable() or ch in "\n\t") for ch in text)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_changes(changes: list[Change]) -> str:
    """The proposal's hash: the path and the exact old and new bytes of every changed file, in path order. An absent
    side is marked apart from an empty one, and each part is length-prefixed, so no two change lists share a stream."""
    h = hashlib.sha256()
    for c in changes:
        for part in (c.path.encode("utf-8"), c.old, c.new):
            if part is None:
                h.update(b"\x00")
            else:
                h.update(b"\x01" + len(part).to_bytes(8, "big") + part)
    return h.hexdigest()


def diff_text(changes: list[Change]) -> str:
    """The text a person reads. A header per file, then its unified diff, with control and non-printing characters
    written out so that every line the person reads is a line the file holds. A file that is not UTF-8 text is shown
    by the SHA-256 of its bytes instead."""
    out = []
    for c in changes:
        status = "added" if c.old is None else "deleted" if c.new is None else "changed"
        try:
            old = None if c.old is None else c.old.decode("utf-8")
            new = None if c.new is None else c.new.decode("utf-8")
        except UnicodeDecodeError:
            shown = [f"{name} sha256 {sha256_of(data)}" for name, data in (("old", c.old), ("new", c.new))
                     if data is not None]
            out.append(f"== {c.path}: {status}, not UTF-8 text; {'; '.join(shown)}\n")
            continue
        hidden = any(_hidden(t) for t in (old or "", new or ""))
        out.append(f"== {c.path}: {status}" + (", contains control characters" if hidden else "") + "\n")
        old_lines = _escape(old or "").splitlines(keepends=True)
        new_lines = _escape(new or "").splitlines(keepends=True)
        out.extend(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{c.path}", tofile=f"b/{c.path}"))
    return "".join(out)


def _bound(node: ast.stmt) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Assign):
        return {t.id for t in node.targets if isinstance(t, ast.Name)}
    return set()


def _names(root: Path, pattern: str, keep: Callable[[str], bool]) -> set[str]:
    """The top-level names that files matching ``pattern`` define. A file that does not parse defines none, so its
    names count as removed: a broken file fails closed."""
    names: set[str] = set()
    for path in sorted(root.glob(pattern)):
        if not path.is_file():  # a folder named like a module defines nothing
            continue
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, ValueError):
            continue
        for node in tree.body:
            names |= {n for n in _bound(node) if keep(n)}
    return names


def assess(library: Path, scratch: Path, changes: list[Change]) -> list[str]:
    """The reasons the harness refuses these changes outright, whatever a person says. Empty means every change may
    wait for a yes. It is a coarse, name-level check and a depth layer, not a guarantee. It refuses a change to
    ``.github/``, a deleted file under ``tests/``, an edit to an existing file under ``tests/``, a new file under
    ``tests/`` that is not a ``test_*.py`` module, and a removed public or test name. A public name is one a module under
    ``unitcraft/`` defines at its top level; a test is a top-level ``test_`` function under ``tests/``."""
    reasons = [f"{GITHUB}/ is not changed by the harness: {c.path}" for c in changes if c.path.startswith(GITHUB + "/")]
    reasons += [f"deletes {c.path}" for c in changes if c.new is None and c.path.startswith(TESTS)]
    reasons += [f"changes the test file {c.path}" for c in changes
                if c.path.startswith(TESTS) and c.old is not None and c.new is not None]
    reasons += [f"adds {c.path}, which is not a test module" for c in changes
                if c.old is None and c.path.startswith(TESTS) and not PurePosixPath(c.path).match("tests/test_*.py")]
    public = _names(library, "unitcraft/*.py", lambda n: not n.startswith("_"))
    gone = public - _names(scratch, "unitcraft/*.py", lambda n: not n.startswith("_"))
    reasons += [f"removes public name {n}" for n in sorted(gone)]
    tests = _names(library, "tests/test_*.py", lambda n: n.startswith("test_"))
    gone = tests - _names(scratch, "tests/test_*.py", lambda n: n.startswith("test_"))
    reasons += [f"removes test {n}" for n in sorted(gone)]
    return reasons


def apply(changes: list[Change], library: Path) -> None:
    """Write every change into the library, or none of them. A new or changed file gets its new bytes and a deleted
    file is removed. The old bytes are held in ``changes``, so any error (a folder where a file goes, a full disk, a
    changed file) puts back each file this call touched, and each folder it made, and then raises the error."""
    touched: list[Change] = []
    made: list[Path] = []
    try:
        for c in changes:
            target = library / c.path
            touched.append(c)  # before the write, so a write that fails part way is put back too
            if c.new is None:
                target.unlink()
                continue
            chain, parent = [], target.parent
            while not parent.exists():
                chain.append(parent)
                parent = parent.parent
            for folder in reversed(chain):
                folder.mkdir()
                made.append(folder)
            target.write_bytes(c.new)
        for c in changes:  # verify: every file now holds exactly the new bytes, or is absent
            target = library / c.path
            found = target.read_bytes() if target.is_file() else None
            if found != c.new:
                raise OSError(f"verify failed for {c.path}")
    except BaseException:
        _restore(touched, library, made)
        raise


def _restore(touched: list[Change], library: Path, made: list[Path]) -> None:
    for c in reversed(touched):
        target = library / c.path
        if c.old is None:
            if target.is_file():
                target.unlink()
        else:
            target.write_bytes(c.old)
    for folder in reversed(made):
        try:
            folder.rmdir()
        except OSError:
            pass


@dataclass(frozen=True)
class Proposal:
    """What the person is asked: the proposal's ID, the finish summary, the files, the diff text as shown and the
    hash of the changed bytes."""

    id: str
    summary: str
    files: tuple[str, ...]
    diff: str
    sha256: str


@dataclass(frozen=True)
class Answer:
    """A person's answer. It counts only for the proposal whose ID and bytes-hash it carries."""

    yes: bool
    proposal_id: str
    diff_sha256: str
    reason: str = ""


Approver = Callable[[Proposal], Answer]


def answer(proposal: Proposal, yes: bool, reason: str = "") -> Answer:
    """The answer to a proposal, bound to the proposal as the person saw it."""
    return Answer(yes, proposal.id, proposal.sha256, reason)


def scripted(*decisions: tuple[bool, str]) -> Approver:
    """An approver that answers the proposals in order, each with a (yes, reason) pair. An unexpected ask raises."""
    queue = list(decisions)

    def approve(proposal: Proposal) -> Answer:
        yes, reason = queue.pop(0)
        return answer(proposal, yes, reason)

    return approve


@dataclass(frozen=True)
class Pending:
    """What a copy still holds when its run ends: the files that never reached a yes, and the never-class reasons."""

    files: tuple[str, ...]
    never: tuple[str, ...]


@dataclass
class Gate:
    """One gate for one library. With ``enforce`` False it observes: it decides and counts as usual, logs what it
    would have done, and returns each tool's own result, so a recorded run replays unchanged. ``approver`` is needed
    only when enforcing. A tool outside the table is refused in both modes, since no recorded run calls one.

    ``classes`` is a harness's own class table (``{"docs__delete_page": "change"}``), read as data. It adds names; it
    cannot reclass a name in ``TOOL_CLASS``. A harness ``change`` tool runs outside the scratch copy, so each of its
    calls asks for its own yes, bound to the call's name and arguments. Left None, the gate is exactly chapter 6's."""

    library: Path
    approver: Approver | None = None
    enforce: bool = True
    log: list[str] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)
    classes: Mapping[str, str] | None = None
    _proposals: int = 0
    _calls: int = 0
    _expected: dict[str, bytes] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.enforce and self.approver is None:
            raise ValueError("an enforcing gate needs an approver")
        self.classes = dict(self.classes or {})
        clash = sorted(set(self.classes) & set(TOOL_CLASS))
        if clash:
            raise ValueError(f"a harness table may not reclass the chapter 6 tools: {clash}")
        bad = sorted(n for n, c in self.classes.items() if c not in (READ, CHANGE))
        if bad:
            raise ValueError(f"a harness class is read or change, not the one given for: {bad}")
        self._expected = _files(self.library)

    def class_of(self, name: str) -> str:
        """The class this gate gives a tool name: from ``TOOL_CLASS``, then the harness's ``classes``, else never."""
        return classify(name, self.classes)

    def moved(self) -> list[str]:
        """The case-relative paths whose bytes differ from what the gate last left in the library, sorted. Only this
        gate's own ``apply`` changes what it expects."""
        now = _files(self.library)
        return sorted(p for p in set(now) | set(self._expected) if now.get(p) != self._expected.get(p))

    def stopped(self, name: str, paths: list[str]) -> ToolResult:
        """The run ends as ``library_changed``. The paths are reported, and nothing is restored."""
        self.counts["library changed"] += 1
        self.log.append(f"library changed around {name}: {', '.join(paths)}")
        why = f"the case library changed around {name}: {', '.join(paths)}; the run stops, and nothing is restored"
        return ToolResult(f"error: {why}", brief="error: library changed", end="library_changed", question=why)

    def runner(self, tool: Tool) -> Callable[[Workspace, BaseModel], ToolResult]:
        cls = self.class_of(tool.name)

        def run(ws: Workspace, args: BaseModel) -> ToolResult:
            if cls == NEVER:  # decided before anything runs, so the tool's own code never does
                self.counts["never calls"] += 1
                self.log.append(f"call refused: {tool.name} is not a tool this harness runs")
                return ToolResult(f"error: {tool.name} is not a tool this harness runs",
                                  brief="error: not a tool this harness runs")
            if cls == PROPOSE:
                return self.propose(ws, args, tool)
            if cls == CHANGE:
                self.counts["change calls"] += 1
                path = str(getattr(args, "path", ""))
                if [p for p in PurePosixPath(path).parts if p != "."][:1] == [GITHUB]:
                    self.counts["never calls"] += 1
                    self.log.append(f"call refused: .github/ is not changed by the harness: {path}")
                    if self.enforce:
                        return ToolResult(f"error: .github/ is not changed by the harness: {path}",
                                          brief="error: .github/ is not changed")
                if tool.name in self.classes:
                    return self.ask_call(ws, args, tool)
            return tool.run(ws, args)

        return run

    def propose(self, ws: Workspace, args: BaseModel, tool: Tool) -> ToolResult:
        """Gate a finish. A copy with no change passes through to the tool. Otherwise the proposal is checked and asked,
        and the tool's own body runs only after a yes (or, when observing, after the decision, to give its result)."""
        changes = pending(self.library, ws.root)
        if not changes:
            return tool.run(ws, args)
        self._proposals += 1
        pid = f"p-{self._proposals}"
        self.counts["proposals"] += 1
        text = diff_text(changes)
        sha = digest_changes(changes)
        head = f"{pid} {len(changes)} files, diff {sha[:12]}"
        reasons = assess(self.library, ws.root, changes)
        if reasons:
            self.counts["held as never"] += 1
            return self._hold(pid, "the harness refuses it: " + "; ".join(reasons), ws, args, tool)
        if not self.enforce:
            self.counts["waiting for a yes"] += 1
            self.log.append(f"{head}: would wait for a yes")
            return tool.run(ws, args)
        self.counts["asked"] += 1
        self.log.append(f"{head}: asked")
        answer_ = self.approver(Proposal(pid, args.summary, tuple(c.path for c in changes), text, sha))
        self.log.append(f"{pid} answer {'yes' if answer_.yes else 'no'}, bound to {answer_.proposal_id} "
                        f"and {answer_.diff_sha256[:12]}")
        if not answer_.yes:
            return self._hold(pid, f"the person said no: {answer_.reason}", ws, args, tool)
        if answer_.proposal_id != pid or answer_.diff_sha256 != sha:
            return self._hold(pid, "the answer is to another proposal or diff", ws, args, tool)
        now = pending(self.library, ws.root)
        if digest_changes(now) != sha:
            return self._hold(pid, "the copy changed after the answer", ws, args, tool)
        try:
            apply(now, self.library)
        except OSError as exc:
            return self._hold(pid, f"apply failed ({type(exc).__name__}); library restored", ws, args, tool)
        self._expected = _files(self.library)
        self.counts["applied"] += 1
        self.counts["files applied"] += len(now)
        self.log.append(f"{pid} applied: {len(now)} files")
        tool.run(ws, args)
        return ToolResult(f"{pid} applied: {len(now)} files", brief=f"{pid} yes, applied {len(now)} files",
                          end="finish", summary=args.summary)

    def ask_call(self, ws: Workspace, args: BaseModel, tool: Tool) -> ToolResult:
        """A harness change tool acts outside the copy, so each call asks for its own yes. The yes counts only for this
        call's name and arguments, as a finish's yes counts only for its diff. Observing, it logs and runs."""
        self._calls += 1
        self.counts["external calls"] += 1
        body = json.dumps({"tool": tool.name, "arguments": args.model_dump()}, sort_keys=True)
        sha = sha256_of(body.encode("utf-8"))
        pid = f"c-{self._calls}"
        if not self.enforce:
            self.counts["waiting for a yes"] += 1
            self.log.append(f"{pid} {tool.name}: would wait for a yes")
            return tool.run(ws, args)
        self.counts["asked"] += 1
        answer_ = self.approver(Proposal(pid, f"call {tool.name}", (), body, sha))
        yes = answer_.yes and answer_.proposal_id == pid and answer_.diff_sha256 == sha
        self.log.append(f"{pid} {tool.name}: {'yes' if yes else 'not approved'}")
        if not yes:
            self.counts["refused"] += 1
            text = f"error: {tool.name} was not approved; nothing was sent to the server"
            return ToolResult(text, brief="error: not approved", end="ask_user", question=text)
        return tool.run(ws, args)

    def wrap(self, tool: Tool) -> Tool:
        """The tool with its runner passed through this gate and the library guard."""
        return replace(tool, run=_guarded(self, tool.name, self.runner(tool)))

    def _hold(self, pid: str, why: str, ws: Workspace, args: BaseModel, tool: Tool) -> ToolResult:
        """Nothing is applied. When enforcing, the reason goes back as the tool result and ends the run as a handoff."""
        self.log.append(f"{pid} not applied: {why}")
        if not self.enforce:
            return tool.run(ws, args)
        self.counts["refused"] += 1
        handoff = f"{pid} was not applied: {why}"
        return ToolResult(f"error: {handoff}", brief=handoff, end="ask_user", question=handoff)

    def settle(self, scratch: Path) -> Pending:
        """What the copy still holds when its run ends. Those changes are dropped; the library is not touched."""
        changes = pending(self.library, scratch)
        return Pending(tuple(c.path for c in changes), tuple(assess(self.library, scratch, changes)))


def _guarded(gate: Gate, name: str, run: Callable[[Workspace, BaseModel], ToolResult]) -> Callable[..., ToolResult]:
    """Compare the library's bytes before and after a tool call. A change the gate did not apply ends the run."""

    def guarded(ws: Workspace, args: BaseModel) -> ToolResult:
        moved = gate.moved()
        if moved:
            return gate.stopped(name, moved)
        try:
            result = run(ws, args)
        except Exception:
            moved = gate.moved()
            if moved:
                return gate.stopped(name, moved)
            raise
        moved = gate.moved()
        return gate.stopped(name, moved) if moved else result

    return guarded


def gated(tools: ToolSet, gate: Gate) -> ToolSet:
    """The same tools, each runner passed through the gate and the library guard. Names, descriptions and schemas are
    unchanged, so a request made with the gated set hashes the same as one made without it."""
    return replace(tools, tools=tuple(gate.wrap(t) for t in tools.tools))


@contextmanager
def library_copy() -> Iterator[Path]:
    """A copy of the case library that a gate may apply to. The book's case folder is never written."""
    path = scratch_copy(CASE)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def replay_ids(task_id: str) -> IdCounter:
    """An ID counter set as the task-set recording had it when this task's run began. Run IDs and tool-call IDs go
    into the requests, so a replay must number its runs as the recording did: one run ID per task, in file order."""
    ids = IdCounter()
    for task in load_tasks():
        if task.id == task_id:
            return ids
        ids.next("run")
    raise ValueError(f"no such task: {task_id}")


def replay_task(task_id: str, gate: Gate, library: Path, ids: IdCounter | None = None) -> Run:
    """Replay one recorded task-set run through the gate, on a copy of ``library``. Pass ``ids`` when replaying the
    set in file order, so the run IDs match the recording; otherwise the counter is set for this task alone."""
    task = load_tasks(only=[task_id])[0]
    model = ReplayModel("task-set", task_id)
    counter = replay_ids(task_id) if ids is None else ids
    return run_task(model, task, gated(V1, gate), max_steps=V1.step_cap, ids=counter, case=library)


def stored_task(task_id: str, gate: Gate, library: Path) -> Run:
    """Run a task-set task with its stored replies copied as a scripted model. The steps are the recorded ones, but
    the tool results come from the copy, so the copy may differ from the recording's."""
    rows = (DATA / "recorded" / "task-set" / "replies.jsonl").read_text(encoding="utf-8").splitlines()
    steps = sorted((r for r in map(json.loads, rows) if r["run"] == task_id), key=lambda r: r["step"])
    task = load_tasks(only=[task_id])[0]
    return run_task(ScriptedModel([r["text"] for r in steps]), task, gated(V1, gate), max_steps=V1.step_cap,
                    ids=replay_ids(task_id), case=library)
