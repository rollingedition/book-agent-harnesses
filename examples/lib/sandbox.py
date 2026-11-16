"""The sandbox for the agent's commands: an argv allowlist, a child with rlimits, a timeout that kills its process group,
an environment built from an allowlist, and, where the kernel allows them, a network namespace and a PID namespace.

Teaching code and defence in depth. It is not a container, and it is not a full sandbox. The primary defence for code
an agent wrote is a container or a virtual machine; chapter 7 explains both and runs neither. What this file adds is
no shell (every command is an argv list and ``shell=False``), the limits the kernel enforces, and the scratch copy the
command runs in, with the checks on top of those.

What each part does, and does not do:

- The allowlist decides which program starts. It does not decide what code that program runs: a test run executes the
  copy's own ``conftest.py`` and plugins unless ``hardened_test_argv`` turns them off, so a listed command can still
  change files inside the copy.
- ``RLIMIT_AS``, ``RLIMIT_CPU`` and ``RLIMIT_FSIZE`` are per process and per file, not per command: a command may start
  several processes, and each gets its own cap. ``RLIMIT_NPROC`` is not set: it counts processes per real user ID and is
  not enforced for root, so it stops nothing here. Only a cgroup (a container, or a systemd scope with ``MemoryMax`` and
  ``TasksMax``) caps a whole command. The wrapper refuses to start a command when it cannot set its limits.
- The group kill stops every process still in the process group. A child that calls ``setsid()`` leaves the group and
  survives it. Where the kernel permits a PID namespace (``isolate_pids``, the default), the kernel kills every process
  in that namespace when the command's first process exits, so such a child is stopped as well. Where no PID namespace
  is permitted, the group kill is the only kill, and a child that left the group survives the sandbox.
- A network namespace removes the IP routes and the host's loopback. A Unix socket at a file-system path stays
  reachable from inside it, and so does anything else the copy can open on the shared file system. Only a container,
  or a mount namespace without the host's sockets, stops that.
- Without a PID namespace, ``/proc/PARENT/environ`` and ``/proc/PARENT/cmdline`` show the harness's launch environment
  and arguments to the command. A PID namespace with its own ``/proc`` hides them.
- Writes and reads outside the copy are not confined here, at the harness's own user ID. Only a container, a virtual
  machine, or a file-system restriction such as Landlock stops that.

Fail closed: ``run_sandboxed(..., require_network_block=True)`` refuses to start a command unless a network namespace
can be made. A namespace probe that times out is not cached, so the next command asks again; it is never read as "no
namespace" and then run without one. ``run_allowed`` asks for the block.
"""
from __future__ import annotations

import os
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .case import scratch_copy
from .tools import clean_env

PYTHON = "python"  # the program name the allowlist uses; it runs as the harness's own interpreter
ALLOWED = (("python", "-m", "pytest", "-q", "-p", "no:cacheprovider"),)  # every listed command is one exact argv
TIMEOUT = 120  # seconds; a command still running then is stopped, and its group killed
MEMORY = 1 << 30  # bytes of address space one process may map (RLIMIT_AS, per process)
CPU = 30  # seconds of CPU time one process may use (RLIMIT_CPU, per process)
FILE_SIZE = 64 << 20  # bytes one process may write to one file (RLIMIT_FSIZE, per file)
GRACE = 2  # seconds to wait for output after a kill: a process that left the group can hold the pipe open
PROBE_TIMEOUT = 30  # seconds for one namespace probe
READY_WAIT = 60  # seconds a check waits for a process it started to report; a bound on failure, not a timing
SETTLE = 10  # seconds a check waits for a killed process to close its pipe
NAMESPACE = "sandbox: network namespace"
NO_NAMESPACE = "sandbox: none"
NET_FLAGS = ("-rn",)  # a new user and network namespace
PID_FLAGS = ("-rn", "--pid", "--fork", "--kill-child", "--mount-proc")  # plus a PID namespace with its own /proc

# Runs in the child, before the command: sets the limits, then replaces this process with the command. The argv is
# ``-c WRAPPER AS CPU FSIZE -- COMMAND...``, so the command's own argv is never parsed here.
WRAPPER = """
import os, resource, sys
as_, cpu, fsize = (int(v) for v in sys.argv[1:4])
try:
    resource.setrlimit(resource.RLIMIT_AS, (as_, as_))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
except (ValueError, OSError):
    sys.stderr.write("sandbox: could not set the limits; the command did not run\\n")
    os._exit(70)
os.execvp(sys.argv[5], sys.argv[5:])
"""

# Programs for the checks below. HOLD writes one byte to its pipe once it runs (readiness), then holds the pipe until
# its stdin reaches end-of-file. GRANDCHILD starts HOLD in the command's own group and waits. ESCAPE starts a child
# that calls setsid(), so it leaves the group, and exits at once; that child holds the pipe and reads its stdin.
HOLD = "import os, sys\nos.write(int(sys.argv[1]), b'r')\nsys.stdin.read()\n"
GRANDCHILD = (
    "import subprocess, sys, time\n"
    f"subprocess.Popen([sys.executable, '-I', '-c', {HOLD!r}, sys.argv[1]], stdin=int(sys.argv[2]),\n"
    "    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=(int(sys.argv[1]),))\n"
    "time.sleep(120)\n"
)
ESCAPE = (
    "import subprocess, sys\n"
    "subprocess.Popen([sys.executable, '-I', '-c', 'import sys; sys.stdin.read()'], stdin=int(sys.argv[2]),\n"
    "    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=(int(sys.argv[1]),), start_new_session=True)\n"
)


class Refused(Exception):
    """A command the allowlist does not list. The text is the reason; it goes back to the model as a tool result."""


class NoNetworkBlock(RuntimeError):
    """The command must not run without a network namespace, and none can be made here."""


@dataclass
class Outcome:
    code: int | None  # None when the time limit stopped the command
    out: str
    timed_out: bool
    group: int  # the process group the command ran in; ``kill_group`` stops everything in it


def allowed_argv(command: str) -> list[str]:
    """Parse a command string once and return its argv if the allowlist lists it, else raise ``Refused``."""
    try:
        argv = shlex.split(command)
    except ValueError:
        raise Refused(f"could not parse the command: {command!r}") from None
    if tuple(argv) not in ALLOWED:
        raise Refused(f"not on the allowlist: {command!r}")
    argv[0] = sys.executable if argv[0] == PYTHON else argv[0]
    return argv


def hardened_test_argv(argv: list[str], work: Path, ini_dir: Path) -> list[str]:
    """The argv a listed test command really runs: ``python -I -m pytest`` with a config written outside the copy.

    ``-I`` keeps the copy off ``sys.path``; ``-c`` takes the harness's config, so the copy's ``pytest.ini`` and its
    plugins do not load; ``--noconftest`` skips every ``conftest.py`` in the copy. The config puts the copy on
    ``pythonpath`` and collects ``tests/`` only. Any other argv is returned unchanged.
    """
    if argv[1:3] != ["-m", "pytest"]:
        return argv
    ini = ini_dir / "pytest.ini"
    ini.write_text(f"[pytest]\ntestpaths = tests\npythonpath = {work}\n")
    return [argv[0], "-I", "-m", "pytest", *argv[3:], "-c", str(ini), "--rootdir", str(work), "--noconftest"]


def kill_group(group: int) -> None:
    """SIGKILL every process in the group. A group that has already gone is not an error."""
    try:
        os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
        pass


_PROBED: dict[tuple[str, ...], bool] = {}


def _probe(flags: tuple[str, ...]) -> bool | None:
    """Whether ``unshare`` with these flags runs here. True and False are cached; None (the probe timed out or could not
    start) is not, so the next command asks again."""
    if flags in _PROBED:
        return _PROBED[flags]
    unshare = shutil.which("unshare")
    if unshare is None:
        _PROBED[flags] = False
        return False
    try:
        probe = subprocess.run([unshare, *flags, "true"], env=clean_env(Path(tempfile.gettempdir())),
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=PROBE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    _PROBED[flags] = probe.returncode == 0
    return _PROBED[flags]


def namespace_state() -> bool | None:
    """True when a network namespace can be made here, False when not, None when the probe has not decided yet."""
    return _probe(NET_FLAGS)


def namespace_available() -> bool:
    """True when ``unshare -rn`` (a new user and network namespace) runs here. Only a definite True counts."""
    return namespace_state() is True


def pid_namespace_available() -> bool:
    """True when ``unshare`` can make a PID namespace with its own ``/proc`` here (with a network namespace)."""
    return _probe(PID_FLAGS) is True


def network_label() -> str:
    """The network the next command gets: its own namespace with no route out, or none the sandbox can add."""
    return NAMESPACE if namespace_available() else NO_NAMESPACE


def _prefix(isolate_pids: bool) -> list[str]:
    """The ``unshare`` words a command starts with: PID and network namespaces where asked and permitted, else only the
    network namespace, else nothing. An empty list means the command runs with the host's network."""
    unshare = shutil.which("unshare")
    if unshare is None:
        return []
    if isolate_pids and pid_namespace_available():
        return [unshare, *PID_FLAGS]
    if namespace_available():
        return [unshare, *NET_FLAGS]
    return []


def _check_limits(timeout: float, memory: int, file_size: int) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout must be a positive number of seconds")
    for name, value in (("memory", memory), ("file_size", file_size)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive number of bytes")


def _spawn(argv: list[str], *, cwd: Path, memory: int, file_size: int, pass_fds: tuple[int, ...], isolate_pids: bool,
           require_network_block: bool, extra_env: dict[str, str] | None, capture: bool) -> subprocess.Popen:
    prefix = _prefix(isolate_pids)
    if require_network_block and not prefix:
        raise NoNetworkBlock("no network namespace can be made here, so the command was not run (sandbox: none)")
    env = clean_env(cwd)
    env.update(extra_env or {})
    limits = [str(memory), str(CPU), str(file_size)]
    return subprocess.Popen([*prefix, sys.executable, "-I", "-c", WRAPPER, *limits, "--", *argv], cwd=cwd, env=env,
                            shell=False, start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                            stderr=subprocess.STDOUT if capture else subprocess.DEVNULL, pass_fds=pass_fds)


def _after_kill(proc: subprocess.Popen) -> bytes:
    """The output read after a kill, waiting at most GRACE seconds. A process that left the group can hold the pipe
    open; then the pipe is closed, and the command's output is what was read before that (nothing, in practice)."""
    try:
        out, _ = proc.communicate(timeout=GRACE)
        return out
    except subprocess.TimeoutExpired:
        proc.stdout.close()
        proc.wait()
        return b""


def run_sandboxed(argv: list[str], *, cwd: Path, timeout: float, memory: int = MEMORY,
                  file_size: int = FILE_SIZE, group_kill: bool = True, pass_fds: tuple[int, ...] = (),
                  isolate_pids: bool = True, require_network_block: bool = False,
                  extra_env: dict[str, str] | None = None) -> Outcome:
    """Run an argv list (never a shell string) with limits, a time limit and an environment from an allowlist.

    ``group_kill=False`` kills only the direct child on timeout, as ``subprocess.run`` does; chapter 7's example uses
    it to show the grandchild that survives. Every other caller leaves it True. ``isolate_pids`` asks for a PID
    namespace where the kernel permits one. ``require_network_block`` raises ``NoNetworkBlock`` instead of running the
    command with the host's network. ``extra_env`` adds names to the command's environment.
    """
    if not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError("argv must be a non-empty list of strings")
    _check_limits(timeout, memory, file_size)
    proc = _spawn(argv, cwd=cwd, memory=memory, file_size=file_size, pass_fds=pass_fds, isolate_pids=isolate_pids,
                  require_network_block=require_network_block, extra_env=extra_env, capture=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        if group_kill:
            kill_group(proc.pid)
        else:
            proc.kill()
        out = _after_kill(proc)
    finally:
        if group_kill:
            kill_group(proc.pid)  # a command's own leftover children go too, on every path
    code = None if timed_out else proc.returncode
    return Outcome(code, out.decode("utf-8", "replace"), timed_out, proc.pid)


def run_allowed(command: str, *, cwd: Path, timeout: float = TIMEOUT, require_network_block: bool = True) -> str:
    """The text the model gets for one command: the refusal, the refusal to run without a block, the time-limit stop,
    or the exit code and output. A listed test command runs as ``hardened_test_argv`` builds it."""
    try:
        argv = allowed_argv(command)
    except Refused as refusal:
        return f"error: command refused: {refusal}"
    with tempfile.TemporaryDirectory(prefix="sandbox-ini-") as ini_dir:
        argv = hardened_test_argv(argv, cwd, Path(ini_dir))
        try:
            result = run_sandboxed(argv, cwd=cwd, timeout=timeout, require_network_block=require_network_block,
                                   extra_env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
        except NoNetworkBlock as reason:
            return f"error: command not run: {reason}"
    if result.timed_out:
        return "error: the command was stopped at the time limit"
    return f"exit: {result.code}\n{result.out}"


@contextmanager
def scratch_dir() -> Iterator[Path]:
    """A scratch copy of the case for one example, removed when the example ends."""
    path = scratch_copy()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _readable_within(fd: int, seconds: float) -> bool:
    """True when the pipe becomes readable (data, or end-of-file) within the bound. Used only where no data is sent."""
    return bool(select.select([fd], [], [], seconds)[0])


def grandchild_survives(work: Path, *, group_kill: bool, isolate_pids: bool = True) -> bool:
    """Start a grandchild in the command's group, stop the command at the kill, and report whether the grandchild lives.

    The grandchild writes a byte once it runs, and the check waits for that byte before it kills anything, so the
    outcome does not depend on how fast the machine is. The pipe reaches end-of-file only when every holder has exited.
    With ``group_kill=False`` only the direct child is killed, and the grandchild lives on until the check releases it.
    ``isolate_pids`` is passed to the spawn; a check that must not depend on the kernel passes False. Both outcomes wait
    the same ``SETTLE`` seconds before they read the pipe.
    """
    hold_r, hold_w = os.pipe()
    ctl_r, ctl_w = os.pipe()
    proc = None
    try:
        try:
            proc = _spawn([sys.executable, "-c", GRANDCHILD, str(hold_w), str(ctl_r)], cwd=work, memory=MEMORY,
                          file_size=FILE_SIZE, pass_fds=(hold_w, ctl_r), isolate_pids=isolate_pids,
                          require_network_block=False, extra_env=None, capture=False)
        finally:
            os.close(hold_w)
            os.close(ctl_r)
        if not _readable_within(hold_r, READY_WAIT) or os.read(hold_r, 1) != b"r":
            raise RuntimeError("the grandchild did not start")
        if group_kill:
            kill_group(proc.pid)
        else:
            proc.kill()
        proc.wait()
        return not _readable_within(hold_r, SETTLE)
    finally:
        os.close(ctl_w)  # the grandchild's stdin reaches end-of-file, and it exits
        os.close(hold_r)
        if proc is not None:
            kill_group(proc.pid)


def escape_survives(work: Path, *, isolate_pids: bool) -> bool:
    """Run a command whose child calls setsid() and holds a pipe, let the command return, and report whether the child
    still lives. The check reads the pipe, so it needs no process table: end-of-file means the child has exited.
    ``isolate_pids`` is passed to ``run_sandboxed``."""
    hold_r, hold_w = os.pipe()
    ctl_r, ctl_w = os.pipe()
    try:
        try:
            run_sandboxed([sys.executable, "-c", ESCAPE, str(hold_w), str(ctl_r)], cwd=work, timeout=READY_WAIT,
                          pass_fds=(hold_w, ctl_r), isolate_pids=isolate_pids)
        finally:
            os.close(hold_w)
            os.close(ctl_r)
        return not _readable_within(hold_r, SETTLE)
    finally:
        os.close(ctl_w)  # releases a child that is still alive
        os.close(hold_r)
