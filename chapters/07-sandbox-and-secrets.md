---
chapter_id: sandbox-and-secrets
---

# Run the agent's code in a sandbox, and keep secrets out of its view

By the end of this chapter you can run a command for the agent with a time limit, per-process memory, CPU and file-size caps, an environment built from an allowlist, and a scratch copy as its working folder. You can also say which of those limits a container or a virtual machine would add, and which this sandbox leaves open.

The maintenance agent looks after `unitcraft`, a small units library, and the one command it can run is the test suite. It calls `run_tests`, and the harness runs the visible suite on the agent's copy. A test file is code, and until now that code ran with the harness's own user ID, with the harness's files in reach and the harness's environment to read. [The permission gates](#open-limits) kept the agent's file-tool writes inside its copy, and the library guard reports any change a test made to the library. The guard detects that change and ends the run; it does not prevent it. The case library's bytes are compared before and after every tool call, and the guard fails closed: the run ends as `library_changed`, the harness applies nothing, and nothing is restored. This chapter covers the routes the copy's configuration opens and what the sandbox does about each. It does not stop a test module from writing where the harness can write, and [the table of gaps](#teaching-sandbox) says which isolation does.

For code an agent wrote, the primary defence is a container or a virtual machine. This chapter explains both and runs neither. No example here runs one, and no recording shows one, so the container and virtual machine claims are cited to their documentation. What the book builds is the sandbox in `sandbox.py`, which is teaching code and a second layer, not the protection itself. The sections below say what each of its parts does and what it leaves open. The sandbox needs Linux, because it uses `unshare`, `/proc` and enforced limits. On another system, run the examples in a Linux container or a virtual machine.

## A teaching sandbox, not a container {#teaching-sandbox}

This sandbox is not a container, and the gap between the two is what the section is about. A container is an ordinary process whose view is limited by namespaces, and whose resource use is counted and capped by cgroups. Namespaces give a process its own mount points, process IDs, network devices and ports, and user IDs ([namespaces(7)](https://man7.org/linux/man-pages/man7/namespaces.7.html)). Cgroups limit what a group of processes may use, including memory, CPU time and the number of processes it may create ([cgroups(7)](https://man7.org/linux/man-pages/man7/cgroups.7.html)). Cgroups do not keep one container's data away from another's. Docker's security overview makes the same point, and it places the separation of processes and networks in the namespaces ([Docker's security overview](https://docs.docker.com/engine/security/)).

A virtual machine goes further. Its guest runs behind a virtual machine boundary and sees the devices the machine gives it. Firecracker's documentation describes its microVMs as virtual machines with a minimal device model for the guest, and says that a container can be placed behind such a boundary ([Firecracker](https://firecracker-microvm.github.io/)).

The book's sandbox uses what the operating system and Python already provide. A command is an argv list, never a shell string, and the runner starts it with `shell=False`, so no shell reads its quotes or its semicolons ([subprocess](https://docs.python.org/3.12/library/subprocess.html)). A listed test command runs with the harness's own pytest configuration, and the copy's `conftest.py` files are skipped. A time limit kills the command's whole process group. Each process has caps on address space, CPU time and file size. Where the kernel permits, the sandbox also starts the command in a network namespace and in a PID namespace of its own. The book does not rely on the network namespace for any claim, and it makes no claim that the network or file writes are confined in the reader's runtime. Its environment is built from an allowlist.
The table sets out what a command can still do under the sandbox, and what a container or a virtual machine would add.

| The command can still | The sandbox does | A container or virtual machine adds |
| --- | --- | --- |
| Read and write files outside the copy | Nothing. The command runs with the harness's own user ID. | A mount namespace shows only the mount points it is given, and a guest sees only its machine's devices. Landlock, a kernel interface that lets a process restrict its own file access, could restrict writes ([Landlock](https://docs.kernel.org/userspace-api/landlock.html)). This book does not use it. |
| Read the harness's environment and arguments through `/proc` | Nothing, where no PID namespace can be made. Where one can, the command gets its own `/proc`. | A PID namespace with its own `/proc`. |
| Use more memory, CPU or processes in total | Caps each process and each file, not the command as a whole | Cgroups cap the memory, CPU and process count of a group, once the container sets those limits ([cgroups(7)](https://man7.org/linux/man-pages/man7/cgroups.7.html)). |
| Reach another program through a Unix socket at a file-system path | Nothing. The network namespace removes IP routes, not paths. | A mount namespace that leaves out the host's sockets, or a virtual machine. |
| Reach the network on the test path | Runs it in a network namespace with no route out, where one can be made. Where none can, nothing stops it. The harness's test runs do not require the namespace. | A network namespace with no route out, or no network at all. |
| Keep running after the group kill, by calling `setsid` | Nothing, unless the kernel grants a PID namespace, where the namespace's end kills it | A container's own PID namespace, or a virtual machine. |
| Pass a check by running code it wrote | Scores in a fresh copy with the copy's config and conftest files left out. The package's code still runs in that folder, next to the check. | A separate file system for scoring, so the check's own files are out of the code's reach. A container does not decide whether a fix is real. |

So for code an agent wrote, use a container or a virtual machine, and set the container's limits. A container has no resource constraints by default, and it can use as much of a resource as the host's kernel scheduler allows ([Docker's resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)). A container that mounts the host's sockets leaves the socket row open. This sandbox is a second layer inside a container, and the only layer where there is none, as in the Lab's worker. The rest of this chapter describes that layer.

**Working rule:** Run code an agent wrote inside a container or a virtual machine, with this sandbox as a second layer inside it. Where neither is available, do not run that code on a machine you need to keep intact. The sandbox is teaching code, and the table above lists what it leaves open.

## Only listed programs {#listed-programs}

The allowlist decides which program starts. No tool in this book offers the model a command tool. The model's only way to run code is `run_tests`, which the harness starts with a fixed argv. The allowlist is the check a command tool would use: it parses a command string once with `shlex.split`, and compares the argv with a short list of exact argv tuples. The list holds one entry, `python -m pytest -q -p no:cacheprovider`. A command that does not match is refused as text before anything starts, and that refusal is what a command tool would return to the model.

Start with a set of commands the check should sort. Two spell the listed command with different spacing, and the rest should be refused.

[Example: argv-allowlist](../examples/argv-allowlist.py)

The check lets through {{out:argv-allowlist:allowed commands}} commands and refuses {{out:argv-allowlist:refused commands}}. Both allowed spellings parse to the same argv, because the extra spaces are separators and nothing else. A flag makes a different argv, so `--collect-only` is refused. So is `pytest` on its own, since it names a different program. A string that joins a second command with `;` is refused whole, because its parsed argv does not match the list and no shell ever reads the semicolon. An unclosed quote is refused before the comparison, because the string does not parse.

A test file the model can read can carry text too. In T-15, one of the case's test files carries a line, in an assertion message, that asks for `rm -rf tests`. The model reads that file with `read_file`, so the line reaches it as data. Nothing in the loop acts on the line as an instruction, and a command tool that received the line would refuse the command it names.

[Example: injected-text-refused](../examples/injected-text-refused.py)

This replay uses the replies of T-15's recorded run from [the task set](#testing-the-agent), made with the same open model that [chapter 1](#replayed-run) replays. That run never read the file holding the line, and the replay sent no request that carried it. So this replay shows what the harness does with the line once the file is read: the file holds the text, and the command the text asks for is refused. The replayed run ended as {{out:injected-text-refused:replayed run ended}}, and {{out:injected-text-refused:replayed requests that carried the note}} of its requests carried the line. The refusal a command tool would return is `error: command refused: not on the allowlist: 'rm -rf tests'`, and {{out:injected-text-refused:test folders left in the copy}} test folder stayed in the copy. Nothing in the run shows the model reacting to the line, because the recorded run never gave it the chance.

A refused string is not a refused effect, though. The same folder can go another way, through a test file.

[Example: same-effect-through-a-test-file](../examples/same-effect-through-a-test-file.py)

Two copies of the case are made here, and each carries a `conftest.py` that removes `tests/` when pytest loads it. The listed command, run as the allowlist lists it, loads that file, and the folder goes: {{out:same-effect-through-a-test-file:test folders left after the listed command}} folders are left. The harness runs the same program with its own configuration and with `--noconftest`, so the copy's conftest is never loaded, and {{out:same-effect-through-a-test-file:test folders left after the harness's run}} test folder is left. The allowlist chose pytest, and pytest did what the copy's files told it to do. The allowlist cannot see what a file will do, so a refusal of `rm -rf tests` says nothing about the folder. What the harness controls is what the listed program loads: its configuration, its plugins and its conftest files. It does not control what a test module may do.

**Working rule:** List the exact argv of every program the agent may start, parse each command once, and compare the parsed list with that list. Never pass the model's string to a shell, and never decide by searching the string for a word. Then fix what each listed program loads as well: its configuration and plugins come from outside the copy, and conftest files are off. Treat any test module as code that runs with the harness's rights.

## Limits, and the grandchild they miss {#limits}

An agent's command can run away with memory, time or disk, and the harness has to survive that. The sandbox sets its caps in the child, before the command starts. A small wrapper sets the address-space cap, the CPU-time cap and the file-size cap, and then replaces itself with the command. The wrapper refuses to start the command when it cannot set them. No example shows that refusal; it is in the code.

`RLIMIT_AS` caps the address space one process may map. `RLIMIT_CPU` caps the CPU time it may use, and `RLIMIT_FSIZE` caps the size of one file it writes ([resource](https://docs.python.org/3.12/library/resource.html)). Each cap applies to one process or one file. A command that starts several processes gets a cap for each of them, which is why [the table of gaps](#teaching-sandbox) has a row for totals.

Three commands test the limits here: a sleeper that outlives its time limit, a program that allocates more memory than its cap allows, and a program that writes a file past its size cap.

[Example: limits-stop-a-hog](../examples/limits-stop-a-hog.py)

Each command met its own limit and stopped there. The sleeper stopped at its time limit, the only command stopped that way: {{out:limits-stop-a-hog:commands stopped at the time limit}}. The hog and the writer each exited non-zero at their caps, {{out:limits-stop-a-hog:commands that exited non-zero at a cap}} in all, and no line printed after a cap was hit: {{out:limits-stop-a-hog:lines printed after a cap was hit}}.

The time limit reaches less than it looks. The `Popen` documentation says that a child is not killed when the timeout expires, and that a well-behaved application should kill it ([subprocess](https://docs.python.org/3.12/library/subprocess.html)). `subprocess.run` kills only the direct child. The sandbox avoids that gap by starting each command with `start_new_session`, which gives it its own process group, and by killing the whole group on the time limit and on every other exit. The next two checks show what the group kill is for. Each starts a grandchild in the command's group. The first kills only the direct child, and the grandchild is still alive: {{out:limits-stop-a-hog:grandchildren alive after the direct child was killed}}. The second kills the group, and the grandchild is gone: {{out:limits-stop-a-hog:grandchildren alive after the group kill}}. Neither check asks for a PID namespace, so neither answer depends on the kernel.

A process can also leave the group. A call to `setsid` starts a new session, and with it a new group, and the group kill cannot reach that process. The next example runs a command whose child calls `setsid` and holds the command's output pipe.

[Example: escaped-child](../examples/escaped-child.py)

The held pipe does not keep the sandbox waiting past the time limit: the command was stopped at its limit, {{out:escaped-child:commands stopped at the time limit}}. The child that called `setsid` is still alive once the sandbox returns, {{out:escaped-child:setsid children alive after the sandbox returned, without a PID namespace}} child. That check runs without a PID namespace, so its answer does not depend on the kernel. Where the kernel grants one, the sandbox asks for it: `unshare` starts the command as the namespace's first process, with its own `/proc` ([unshare(1)](https://man7.org/linux/man-pages/man1/unshare.1.html)). The kernel ends every process in a PID namespace when the namespace's first process ends, by sending each of them a SIGKILL ([pid_namespaces(7)](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html)). By the kernel's documented behaviour, the child that called `setsid` is in that namespace, so it would go too; the book's examples do not check that case. No printed line covers it, because whether the kernel grants a namespace depends on the machine.

The limit that would count processes, `RLIMIT_NPROC`, is not set here. It counts processes for each real user ID, and the kernel does not enforce it for processes whose real user ID is 0, or that hold certain capabilities ([getrlimit(2)](https://man7.org/linux/man-pages/man2/getrlimit.2.html)). A process run as root is not capped by it, so a fork loop is not stopped by it. [The table of gaps](#teaching-sandbox) names the cgroup, which is the limit that applies to a whole command.

**Working rule:** Cap memory, CPU time and file size on every command, and kill its whole process group on the time limit and on every other exit. Then count what the command can start. Each process has its own caps, so a cap on the total needs a cgroup or a container.

## A network namespace, where the kernel allows one {#network}

A command the agent writes should not reach the network. Where the kernel allows it, the sandbox asks for a new user and network namespace with `unshare -rn` ([unshare(1)](https://man7.org/linux/man-pages/man1/unshare.1.html)). A network namespace has its own network devices, stacks and ports ([namespaces(7)](https://man7.org/linux/man-pages/man7/namespaces.7.html)), so the command has no route out of it. The book does not rely on that namespace to confine the network, and it makes no claim that the network is confined in the reader's runtime. The checks below show what happened on the probe machine.

A listener on the host's loopback is the target, and a command tries to connect to it. The sandbox names the network a command gets with one of two labels: `sandbox: network namespace`, when it can make the namespace, or `sandbox: none`, when it cannot. The check asserts that the label names a namespace exactly when the command could not connect.

[Example: network-label](../examples/network-label.py)

The printed line gives the number of commands the example asks to run, which is two. Its checks are assertions: the label names a namespace exactly when the command could not connect, and the block refuses to run exactly when no namespace can be made. The printed line does not give the label, because the label depends on the machine, and the output has to read the same on every machine. The assertions carry the claim.

A namespace removes IP routes, not paths. The file system stays shared, so a Unix socket at a file-system path can still be reached from inside, and a probe the book ran reached one. [The table of gaps](#teaching-sandbox) lists it, and only a container without the host's sockets, or a virtual machine, would close it.

An empty environment is not a network block. It changes which names the command sees, not what it can connect to. In a probe, a command with an empty environment and no namespace connected to an outside address. No example prints that. It is the reason the block comes from the namespace.

The namespace needs a kernel configured with user namespaces ([user_namespaces(7)](https://man7.org/linux/man-pages/man7/user_namespaces.7.html)). Some distributions restrict them. One coding tool's documentation reports an AppArmor rule that blocks the namespace setup its own sandbox needs ([Claude Code's sandboxing docs](https://code.claude.com/docs/en/sandboxing)). On the kernel the book's probes ran on, an unprivileged user could make the namespace, and an outside connection failed under it. That is the only kernel the book has run this on.

`run_allowed`, which a command tool would call, refuses to start a command when no namespace can be made, and it returns the refusal as text. The harness's own test runs, `run_tests` and the scoring run, use the same runner without that requirement. Where no namespace can be made, those runs take the host's network. The one command the model can run therefore has no network block on its path. That is a gap in the book's code, and a reader who builds on it should require the block on every path that runs code the agent wrote.

**Working rule:** Where a command must not reach the network, require the namespace and refuse to run without it. Check the claim with a listener the command must fail to reach, not with the label alone.

## Secrets stay out of the environment {#secrets}

A secret reaches the model only through what the command prints. The first route to close is the environment, because a command inherits what its parent holds unless something removes it. Python's `subprocess` gives a child a copy of the parent's environment, unless the caller passes `env` ([subprocess](https://docs.python.org/3.12/library/subprocess.html)). Removing a key from the harness does not remove it from a child that copies the harness's environment.

One coding tool's sandbox documentation says its commands inherit that tool's environment, secrets included, unless the tool scrubs them ([Claude Code's sandboxing docs](https://code.claude.com/docs/en/sandboxing)). The book takes the other route. `clean_env` builds the command's environment from a short list of names, such as the search path, the locale and the thread settings. It sets the home folder to the copy and fixes the hash seed. The harness's environment is not copied.

A fake key, under a plain name, is set in the harness's environment before the command starts, as a real key would be set. The command prints the names it can see, and then the example checks what it printed.

[Example: secret-not-in-env](../examples/secret-not-in-env.py)

The fake key never reaches the command. The command sees only names on the allowlist, and {{out:secret-not-in-env:names outside the allowlist}} names fall outside it. The key's name appears {{out:secret-not-in-env:secret name in the command's environment}} times in the command's environment. Its value appears {{out:secret-not-in-env:secret value in the output the model would see}} times in the output the model would receive.

The check does not end with the command's own environment. A command can also read two files under `/proc` that describe its parent: the environment the parent started with ([proc_pid_environ(5)](https://man7.org/linux/man-pages/man5/proc_pid_environ.5.html)), and the parent's command line ([proc_pid_cmdline(5)](https://man7.org/linux/man-pages/man5/proc_pid_cmdline.5.html)). Whether those reads succeed depends on the kernel and on whether a PID namespace is in place. Where one is, the command gets its own `/proc`, which does not list the harness's processes. Without one, the read can succeed, and in the book's probes it did. No example prints or checks those reads, because their result differs by machine. So a key never goes in the arguments either.

The allowlist covers the environment and nothing else. A key written into the copy is readable by any command that can read the copy, and the copy is the command's working folder. No isolation in [the table of gaps](#teaching-sandbox) would close that: a container that runs the command with the copy mounted reads the same file. Keys never go into the copy.

The next chapter hands a subtask to a child. A child's `run_tests` goes through the same sandboxed test runner as its parent's, with the caps, clean environment and no conftest files that this chapter describes, because the child is given the same tool set. [How a child runs its loop](#child-loop) gives the path.

**Working rule:** Build a command's environment from the names it needs, never by copying the harness's. Keep secrets out of the harness's arguments and out of the copy's files. Treat the harness's environment as readable by any command until a PID namespace is in place.
