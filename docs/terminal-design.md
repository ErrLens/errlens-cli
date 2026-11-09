# Stage 7.1: interactive execution design

This section records the stage 7.1 research before implementation. The current
Windows implementation and its limitations are described in
[Windows ConPTY notes](windows-conpty.md); POSIX PTY is also implemented.

## Evidence and current execution path

Audited runner.py, capture.py, service.py, cli.py, both shell integration modules,
and runner/CLI/shell tests. The current flow is:

```
shell wrapper -> CLI -> Popen(argv, shell=False)
                         | stdin: inherited
                         | stdout PIPE -> reader -> original stdout + bounded tail
                         | stderr PIPE -> reader -> original stderr + bounded tail
                         -> wait/status -> analysis -> explanation on stderr
```

The readers use binary, unbuffered pipes, 64 KiB maximum reads and explicit output
flushes. POSIX select and Windows PeekNamedPipe avoid indefinitely blocked reads.
Partial writes are retried. There is no cross-stream ordering guarantee. Stdin
is inherited, not copied by Runner. Its isatty value therefore depends on the
caller; stdout and stderr are pipes regardless of the caller's terminal.

No window-size propagation or SIGWINCH handler exists. A child can still inspect
an inherited stdin fd if it is a terminal, but on POSIX start_new_session removes
the normal controlling-terminal relationship. Consequently inherited stdin does
not guarantee a usable interactive session or /dev/tty.

On POSIX the child starts a new session; cancellation sends SIGINT to its process
group, then SIGKILL after one second. Windows uses CREATE_NEW_PROCESS_GROUP,
CTRL_BREAK_EVENT and forced termination of the main child. Signal handlers are
restored. Arbitrary detached descendants are not guaranteed to be collected.
Post-exit pipe drain has a one-second timeout; wait-after-kill has a two-second
timeout and each reader join a half-second timeout. A permanently blocked output
sink remains a limitation: daemon readers cannot make every arbitrary write
cancellable. These deadlines are pipe-mode policy, not a ready-made PTY policy.

Normal return codes are preserved. Runner retains negative POSIX signal codes;
CLI maps them to 128+signal and user cancellation to 130. Missing executables,
permission failures, other Runner failures and broken pipes use 127/126/125/141.
Analysis/rendering failure does not replace the already completed child's code.

Capture retains the last 1 MiB of each stream independently and marks truncation.
It is byte-bounded, not line-bounded; decoded copies use replacement for invalid
bytes. This is not a 2 MiB total-process memory ceiling: chunks, copies, decoded
strings and diagnostics require additional bounded-by-input memory. ANSI is
forwarded unchanged and stripped only for analysis. Child buffering cannot be
forced by the parent; flushes cannot recover bytes not yet emitted by the child.

## Reproduced experiments

`experiments/terminal_probe.py` is a standalone POSIX research program, deliberately
outside src and automatic pytest discovery. It uses a fresh process with pty.fork,
deadline-based reads, process reaping and descriptor cleanup. It never changes
the user's terminal modes. Run in an installed Linux environment:

```
python experiments/terminal_probe.py
```

Observed on Ubuntu 24.04/WSL with Linux Python 3.12:

| Probe | Existing pipe Runner | Isolated PTY |
| --- | --- | --- |
| stdin/stdout/stderr isatty | False/False/False with piped input | True/True/True |
| input | received answer from inherited input pipe | received answer through master |
| controlling terminal | not established by Runner | child opened /dev/tty |
| resize | no transport mechanism in code | child reported 101 columns, 33 rows after ioctl |
| Ctrl+C | existing signal tests cover cancellation | byte 0x03 triggered child SIGINT handler |
| exit | 7 | handler deliberately returned 23 |
| ANSI | exact escape bytes on stderr | present in combined terminal output |
| NUL and 0xff | preserved on stdout | observed, but newline became CRLF |
| streams | independent stdout/stderr | merged with terminal input echo |

Windows Python 3.13 pipe probe also returned 7, three false isatty results,
successful input, original NUL/0xff and ANSI bytes. The ordering of print and
os.write differed due to buffering. Windows exports CreatePseudoConsole,
ResizePseudoConsole and ClosePseudoConsole on this machine. This checks API
availability only: no ConPTY session was created. macOS was not tested here.
Actual terminal keyboard input, full-screen applications, Windows ConPTY and an
interactive Python REPL are not claimed as experimentally validated.

## Recommended modes and CLI contract (proposal)

Keep pipe mode as the default. Add `errlens run --terminal-mode pty -- python`
and `--terminal-mode pipe` before COMMAND. The pty name selects POSIX PTY or
Windows ConPTY by platform; help must state the merged-stream contract. Existing
syntax and `--no-explain` remain valid. Do not introduce auto-selection initially.

Explicit PTY request without backend support or usable host input/output terminal
should fail clearly before launching the child, rather than silently changing
semantics. A future explicit auto mode could choose pipe before launch when its
prerequisites fail. Never relaunch a partially executed command as a fallback.
Shell functions should continue requesting default pipe mode; PTY opt-in needs a
separate later decision. PowerShell functions can themselves turn native streams
into object/text pipelines and obscure TTY handles: running the CLI directly is
the first supported interactive path, even from PowerShell 7.

Both PTY variants produce a combined terminal stream on parent stdout, while
ErrLens-owned notices remain on stderr. Separate original stdout/stderr and binary
identity are explicitly unavailable. Two PTYs, one per stream, would break the
single-terminal model and are not recommended.

Reuse TailBuffer for one 1 MiB terminal tail. Do not store merged bytes as fake
stderr. A small terminal capture result should supply CapturedData.combined and
combined_truncated. Factor a data-level service entry point only when implementing
this transport, leaving analyze_capture as the compatibility adapter.

ANSI stripping alone does not reconstruct a screen: CR overwrites, cursor moves,
alternate screens, echo and partial escape sequences can destroy textual traceback
structure. Begin with conservative post-exit analysis of coherent terminal text;
reject/mark uncertain ambiguous records. Never replay an escape sequence twice.
Forward raw transport output only once; diagnostic copies never control the screen.

Important: interactive Python can print an exception and still exit with code 0.
The existing explain_capture intentionally suppresses successful/interrupted
executions, and combined-stream analysis requires failed Python context. Transport
support alone will NOT make REPL exceptions automatically explain themselves.
Define REPL diagnostics as a separate later feature; preserve the current success
policy in the initial transport implementation. Also wait until terminal restoration
before printing a post-exit card so it is not written into an alternate screen.

## POSIX design

Use pty.openpty to allocate master/slave, initialize size from the host terminal
with TIOCGWINSZ/TIOCSWINSZ, and close every unused descriptor promptly. openpty
alone does not grant the child a controlling terminal. Recommended launch path:
a small fresh Python helper launched by Popen without shell=True, with the slave
as fd 0/1/2 and start_new_session=True. The single-threaded helper acquires its
controlling slave using TIOCSCTTY, sets/checks foreground process-group ownership,
closes extra fds and execs the supplied argv. Validate the helper path on macOS.
This avoids Python preexec_fn in a threaded parent. Failure before exec must be
reported separately from an ordinary target exit.

Compare with forkpty/pty.fork: it supplies the controlling-terminal setup, but
forking a process with existing threads or macOS higher-level frameworks is unsafe.
It is acceptable for the isolated probe, not an unconditional production choice.
pty.spawn is convenient but insufficient for bounded cancellation, EOF handling,
capture and explicit ownership; its stdin-EOF behavior can wait indefinitely.
See the [Python pty documentation](https://docs.python.org/3.13/library/pty.html).

For the host tty, snapshot termios, enter raw input mode for forwarding, and restore
in finally on every supported exit. In raw mode, forward Ctrl+C as byte 0x03 once:
the slave line discipline delivers SIGINT to its foreground process group. Do not
also send SIGINT from the parent handler for the same key. External SIGINT and API
cancellation need a separate route to the slave foreground group, with bounded
escalation. Job-control children may have a different foreground group from the
initial process: do not always target the original child PID. Terminal signal
behavior is described in [pty(7)](https://man7.org/linux/man-pages/man7/pty.7.html).

A selector loop copies bounded chunks between host input, master and host output;
retain partial-write suffixes with bounded queues/backpressure. SIGWINCH records
a pending resize; normal loop code reads the host size and applies TIOCSWINSZ.
Test that this delivers SIGWINCH to the correct foreground group without duplicate
manual delivery. Empty input from a pipe is not a portable PTY half-close: canonical
VEOF has different semantics in raw programs. Initially require an interactive
host tty and handle Ctrl+D as input; do not close master merely because stdin ends.

EOF can be an empty read or, on Linux after slave closure, EIO. Correlate EIO with
child/descriptor state; don't swallow every I/O error. macOS EOF handling must be
tested independently. Drain remaining output, reap via waitpid/process wait, close
master/slave, restore tty settings and signal handlers. Add leak-count tests.

## Windows design and implementation choices

ConPTY requires Windows 10 1809 or newer; discover exports at runtime. It takes
UTF-8 text/VT input and output, not arbitrary binary application stdout/stderr.
Create synchronous pipes, CreatePseudoConsole, initialize a STARTUPINFOEX attribute
list with PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE and launch through CreateProcessW.
Pass an explicit executable and correctly quoted argv, never a command interpreter
implicitly. Close parent's unused pipe ends and own process/thread/HPCON handles.
Use ResizePseudoConsole for size changes. Details:
[CreatePseudoConsole](https://learn.microsoft.com/en-us/windows/console/createpseudoconsole),
[session lifecycle](https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session),
[resize](https://learn.microsoft.com/en-us/windows/console/resizepseudoconsole).

Input writer and output reader must be independent to avoid pipe deadlocks. Host
console modes need snapshot/restoration, Unicode input handling and a resize-event
path. Choose the VT-input route for Ctrl+C and verify ENABLE_PROCESSED_INPUT and
client foreground behavior experimentally; don't equate it with Runner's current
CTRL_BREAK_EVENT strategy. A forced-stop path may use a Job Object to bound process
tree cleanup, with an explicit policy for breakaway/detached processes.

ClosePseudoConsole has OS-version-dependent blocking behavior. Continue draining
output on a different thread during close; do not use output EOF as the sole child
completion signal. On older Windows, stopping the reader before close can deadlock.
See [ClosePseudoConsole](https://learn.microsoft.com/en-us/windows/console/closepseudoconsole).

| Choice | Benefit | Cost / decision |
| --- | --- | --- |
| ctypes + Windows APIs | no external runtime package; direct lifecycle control | substantial ABI, handle, quoting, cancellation and console-mode work |
| optional pywinpty backend | existing ConPTY wrapper | native wheels, version-specific read/close behavior and fallback policy need qualification |
| pexpect for POSIX | useful interaction/test facilities | not required for a simple transport; adds dependency |

Recommend standard-library POSIX first, then a separate Windows backend spike.
Evaluate pywinpty before committing to handwritten ctypes. Its metadata permits
Python >=3.10, and its source build uses Rust/maturin; this is not evidence of
working wheels/API behavior on every 3.11–3.13 architecture. Require explicit
ConPTY selection rather than silent legacy winpty fallback. Sources:
[pywinpty metadata](https://raw.githubusercontent.com/andfoy/pywinpty/master/pyproject.toml),
[project documentation](https://github.com/andfoy/pywinpty).
No dependency was installed for this research.

## Stage 7.2 implementation and acceptance plan

1. Approve the merged-output, EOF, Ctrl+C and success/REPL contracts. Add a mode
   selector without changing default behavior; unavailable modes fail before spawn.
2. Implement POSIX allocation/helper/exec and one bounded combined capture. Verify
   three tty fds, controlling tty, input, foreground group and normal/signalled exit.
3. Add bounded relay/backpressure, resize and cancellation; then host raw-mode
   restoration with tests for exceptions and broken output. No inherited fd leaks.
4. Qualify Linux and macOS independently, including repeated start/stop, EOF/EIO,
   Unicode split across reads, echo, CRLF, ANSI, long logs and Ctrl+C without double
   signals. Test Python REPL input/edit/EOF separately from explanation policy.
5. Spike native ConPTY vs pywinpty in isolation. Verify Python 3.11/3.12/3.13,
   supported architectures, Windows 10/11 lifecycle differences, UTF-8/VT, resize,
   input/cancel, client exit code, repeated cleanup and handle counts.
6. Integrate only a qualified Windows backend. Preserve all pipe regressions and
   existing shell defaults. Document unsupported hosts and explicit errors.

Automated PTY harnesses must own their own tty/session and never alter CI runner
tty state. CI covers protocol behavior; manual acceptance must include Windows
Terminal/PowerShell 7, Linux Bash, macOS Terminal/Zsh, narrow windows, resize storms,
Python readline/editing, interrupted startup and cancellation while output is busy.
Full-screen alternate-buffer applications are a later acceptance tier, not an
initial transparency claim. No terminal emulator library is required initially;
screen reconstruction, if later needed, is a separate dependency decision.

Historical open decisions from stage 7.1: minimum Windows build and architectures; optional library version;
ConPTY key translation and EOF policy; detached-process cleanup; behavior when
host stdout is redirected; final combined-tail representation; limits of ANSI
normalization; future REPL explanation timing. These are proposals, not tested
production guarantees. This research stage did not start implementation of stage 7.2.

## Stage 7.2.2 implementation decision

The Windows backend now uses native ctypes with a disposable ConPTY owner and an
atomic kill-on-close Job Object assignment. It adds no dependency. The owner
boundary permits bounded termination despite older ClosePseudoConsole behavior;
the frontend restores console modes and uses the existing terminal capture and
analysis service. POSIX PTY is preserved, and pipe remains the default everywhere.
See [Windows ConPTY implementation and acceptance notes](windows-conpty.md) for
the library comparison, resource lifecycle, deadlines, limits and manual checks.
