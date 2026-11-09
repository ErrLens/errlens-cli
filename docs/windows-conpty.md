# Windows ConPTY backend (stage 7.2.2)

## Choice and scope

The implementation uses standard-library ctypes and the Windows ConPTY API.
Minimum OS: Windows 10 1809 (build 17763); Windows 11 is also targeted. This
adds no pip dependency, wheel architecture constraint or compiler requirement.
CPython 3.11–3.13 is the intended CI matrix; local verification is recorded below.

pywinpty was evaluated against its current
[PtyProcess source](https://github.com/andfoy/pywinpty/blob/main/winpty/ptyprocess.py).
It provides resize, input and exit status, but its high-level adapter adds a
socket/reader thread, sets `closed` during `isalive()`, and has unbounded wait and
decode paths. Qualifying/replacing those paths and native wheel availability
would add lifecycle and packaging risk. The native API gives explicit ownership
of process, pipe, job and pseudoconsole resources without a library fallback.
No pywinpty package was installed. Other wrappers were not added.

This is an explicit transport for `errlens run --terminal-mode pty -- python ...`.
The pipe Runner, shell integration defaults and POSIX PTY implementation are
unchanged. Shell profiles are never touched by terminal mode.

## Ownership and transport

1. The frontend validates real console input/output handles and snapshots their
   modes. It enables VT output and unprocessed VT input, reads Unicode with
   ReadConsoleW (including split UTF-16 surrogate pairs), and polls the visible
   window size. Redirected host stdin/stdout fail before launching the command.
2. A short-lived helper owns ConPTY and every native HANDLE. The helper uses an
   independent hidden console, insulating it from host Ctrl+C without passing
   CREATE_NEW_PROCESS_GROUP's ignored-Ctrl+C state to clients. It uses the base
   CPython executable and the current import path: the Windows venv redirector
   must not sit between Popen.kill()/wait() and the actual owner.
3. Synchronous anonymous pipes connect to CreatePseudoConsole. CreateProcessW
   receives an explicit native executable and `subprocess.list2cmdline` argv,
   cwd, the inherited environment, STARTUPINFOEX and two process attributes:
   PSEUDOCONSOLE and JOB_LIST. The latter assigns the kill-on-close job atomically
   at creation, eliminating a suspended-client/assignment race. The job does not
   allow breakaway. Null standard handles plus STARTF_USESTDHANDLES prevent the
   helper's redirected protocol pipes from becoming client stdout/stdin.
4. A bounded binary protocol carries input, size, output, startup errors, the
   actual DWORD exit status and a completed-cleanup record. Maximum frame is
   64 KiB, host input chunk 4 KiB, and each queue has at most 16 entries.
   Independent input writing and output draining avoid full-pipe deadlocks.
   TerminalCapture retains only the existing bounded combined tail (1 MiB by
   default). Output is forwarded once, without writing output logs to disk.
5. On client exit, the helper reports status, terminates remaining job members,
   and closes HPCON on a separate thread while continuing to drain output.
   It then closes all remaining HANDLEs. Close/drain has a two-second deadline;
   the frontend permits four seconds after status and can terminate the owner.
   Startup has a 15-second deadline, with no execution-duration limit.
6. Cleanup waits at most 0.2 seconds for graceful owner exit, then kills it and
   waits at most two seconds. Synchronous frontend I/O is cancelled and reader/
   writer joins are each bounded to 0.5 seconds. The console input reader is
   cancelled and joined before restoring both saved console modes. The helper
   also watches frontend death, so an external timeout does not leave it running.
   Killing the owner closes its noninherited job handle and terminates clients.

Raw Ctrl+C travels as VT input to the isolated client console, not as a broadcast
console event. A child handler's normal exit status is preserved. Windows
CONTROL_C_EXIT and an external frontend SIGINT suppress explanations and use the
existing CLI interruption code 130. External frontend interruption allows one
second for the child before owner/tree termination. No failed transport retries
the user command. Startup/transport errors use ErrLens errors, distinct from
child failures; batch files are refused rather than implicitly invoking cmd.exe.

Native lifecycle references:
[creating a session](https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session),
[ClosePseudoConsole](https://learn.microsoft.com/en-us/windows/console/closepseudoconsole),
[process attributes including JOB_LIST](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute),
[redirected standard handle caveat](https://github.com/microsoft/terminal/discussions/15814).
ClosePseudoConsole can block on older Windows releases; isolating the owner is
what provides a termination deadline across that API boundary.

## Diagnostics and limits

ConPTY output is UTF-8 terminal text with VT sequences and merged streams, not
binary stdout/stderr. Echo, CRLF, NUL/invalid-byte conversion, cursor addressing,
title changes, wrapping and redraw are expected. Original bytes are neither
promised nor sanitized. Explanations still go to the frontend stderr, in Russian
or English, after modes are restored. Success/REPL exit zero and --no-explain
retain their existing policy. ANSI resets after a final newline no longer make
an otherwise complete traceback look incomplete; explanation rules are unchanged.

There is no screen emulator. Complex redraws/wrapped diagnostics may be incomplete
or unrecognized. Arbitrary full-screen apps, alternate buffers, job control,
Ctrl+Break, EOF/editing conventions across hosts and arbitrary PowerShell pipelines
are not transparency guarantees. A permanently blocked external output sink can
still block the frontend write. Restoring console modes does not undo a child's
screen/title changes, and force-killing the frontend cannot restore its modes.
Restrictive enclosing Job Objects can make Windows reject client creation;
ErrLens reports the API error and does not fall back to pipe or legacy winpty.

## Automated and manual acceptance

The Windows test harness starts each scenario in a disposable process with a
30-second outer timeout. It exercises real ConPTY headlessly and nests a real
console for the CLI/input frontend. It checks all three isatty values, interactive
input, Unicode, ANSI, quoted/spaced arguments, Unicode cwd, resize, Ctrl+C, large
DWORD statuses, stdout streaming, explanations and redirected stderr, no-explain,
success, binary data without crashing, capture limits, repeated HANDLE/thread
counts, failed launches, no transport retry, descendant cleanup, console-mode
restoration and PowerShell 7 without loading profiles. Ordinary pipe regressions
remain in the full suite. Non-Windows systems skip these native tests.

Manual checks in Windows Terminal / PowerShell 7 and VS Code's terminal:

```powershell
errlens run --terminal-mode pty -- python -c "import sys; print([s.isatty() for s in (sys.stdin,sys.stdout,sys.stderr)]); print(input('Name: '))"
errlens run --terminal-mode pty -- python -c "print(undefined_variable)"
errlens run --terminal-mode pty --lang en -- python -c "print(undefined_variable)"
errlens run --terminal-mode pty --no-explain -- python -c "print(undefined_variable)"
errlens run --terminal-mode pty -- python
```

Enter Unicode and quoted text, edit a line, resize the window repeatedly and use
Ctrl+C during input and output. Exit the REPL normally; check `$LASTEXITCODE` and
that typing/echo/line editing still work after success and interruption. Try
redirecting stdout: terminal mode should refuse it; default pipe mode should
continue to work. Repeat on Windows 10 and each target terminal host. These manual
checks and an actual GitHub Actions matrix run remain acceptance work, not claims
made by the isolated local harness.

## Local verification, 2026-11-09

| Environment / check | Result |
| --- | --- |
| Windows 11 build 26300 x64, CPython 3.13.15, full pytest | 291 passed, 20 skipped |
| Windows CPython 3.12.10, ConPTY + terminal + pipe integration subset | 33 passed, 11 skipped |
| Python 3.12, final affected interruption/mode cases | 3 passed |
| Ubuntu 24.04 WSL, Python 3.12.3, affected import + POSIX PTY rerun | 11 passed, 1 skipped |
| WSL selected pipe/CLI/analyzer regressions | passed; initial portable-import failure fixed and rerun above |
| Strict mypy, Windows and Linux platform targets | passed, 21 source files |
| Native Python 3.12 mypy and WSL mypy | passed |
| pip check, development and installed-wheel environments | passed |
| Wheel build, isolated setuptools backend | passed, version remains 0.1.0 |
| Installed wheel outside checkout, ConPTY + entry-point tests | 25 passed |

Python 3.11, Windows 10, ARM64/32-bit, macOS and physical terminal hosts were not
locally qualified. The existing GitHub Actions Windows/Linux/macOS 3.11–3.13
matrix will discover the new tests automatically, but has not run this change.
Its Windows jobs need functioning ConPTY and permission to create nested jobs;
tests have per-scenario outer timeouts and no dependency on an interactive CI tty.
The implementation is ready for stage 7.2.3 review/acceptance, subject to that
matrix and target-host manual checks. No next-stage work, profile installation,
commit, push or release publication was performed.

Files changed in stage 7.2.2 (earlier POSIX stage changes are retained):

- `src/errlens/_conpty.py`: lazy Win32 bindings, handles, job and native session.
- `src/errlens/_conpty_worker.py`: bounded protocol, input/output and owner lifecycle.
- `src/errlens/conpty_runner.py`: frontend relay, console modes, size and cancellation.
- `src/errlens/pty_runner.py`: Windows dispatch only; POSIX behavior preserved.
- `src/errlens/cli.py`: terminal-mode help includes ConPTY.
- `src/errlens/analyzers/python.py`: strip VT before checking final newline.
- `tests/integration/test_conpty.py`: isolated real Windows scenarios.
- `tests/integration/test_pty.py`: name/skip reason reflect the console requirement.
- `tests/unit/test_python_analyzer.py`: regression for trailing VT resets.
- `README.md`, `docs/terminal-design.md`, `docs/windows-conpty.md`: usage, choice,
  lifecycle, validation and limitations.
