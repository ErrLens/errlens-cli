# Stage 7.3: terminal acceptance for 0.1.0

**Stage 7.3 closed with documented limitations (maintainer confirmation, 2026-11-10).**
Verdict: READY for preparation of release 0.1.0, not authorization to publish.
See **Release-critical assessment**
at the end for the evidence and classification of remaining gaps. Earlier
checklists are an optional coverage inventory, not mandatory release gates.

User reports cover three WSL host/shell combinations; VS Code WSL Zsh and the
explicitly unconfirmed scenarios retain NOT TESTED. No manual status is promoted
because an automated test passed. Latest evidence update: 2026-11-10.
Windows Terminal and VS Code ConPTY results below are user-reported manual PASS.
No confirmed blocking product defect is known. No release action is authorized.

Baseline: `84dbb9c927b1b0eaf3ac6efc50863b9f0ef72836`.
Actions #6 passed all 11 jobs. That is automated coverage, not physical-host
acceptance. Readiness is assessed from the combined evidence below.
No real user profile, execution policy, global package or production code is
changed by this procedure. Use disposable shell sessions, then close them.

## Setup and temporary scripts

The helper `experiments/manual_acceptance.py` creates ten UTF-8 scripts in a
new OS temporary directory and prints its path. It never overwrites existing
files. Run `--check` for safe automated pipe checks with automatic cleanup;
without that option, keep the printed directory for manual checks. Scripts that
wait or ask for input are never run by `--check`. `syntax.py` is intentionally
invalid Python. `once.py` appends one line to a marker beside itself, not to the
project. After acceptance, remove only the printed temporary directory.

For Windows Terminal and VS Code, open a new PowerShell 7 terminal and start
`pwsh -NoProfile`. In each host independently:

```powershell
Set-Location D:\Projects\ErrLens
$runtime = (Resolve-Path .venv\Scripts\python.exe).Path
$env:PATH = "$PWD\.venv\Scripts;$env:PATH"
$trial = (& $runtime .\experiments\manual_acceptance.py).Trim()
$mode = 'pipe'
errlens --version
errlens run --help
```

Expect version 0.1.0 and the documented `--terminal-mode`, `--lang` and
`--no-explain` options. No new acceptance subcommand exists in ErrLens.

For WSL Ubuntu 24.04, test Bash and Zsh separately in both Windows Terminal and
VS Code's WSL terminal. Start `bash --noprofile --norc` or `zsh -f`, then run:

```sh
cd /mnt/d/Projects/ErrLens
source .venv-linux/bin/activate
runtime="$PWD/.venv-linux/bin/python"
trial=$("$runtime" experiments/manual_acceptance.py)
mode=pipe
errlens --version
errlens run --help
```

Activate inside the selected shell; do not inherit Bash prompt escapes into Zsh.
These instructions use the existing local environments, not a global install.

## Exact command sets

Run P1–P10 twice: once with `$mode = 'pipe'`, then `$mode = 'pty'`.
In Bash/Zsh use `mode=pipe`, then `mode=pty`. Immediately after each command,
inspect `$LASTEXITCODE` (PowerShell) or `echo $?` (Bash/Zsh); do not run another
native command before reading the status. A child handler may return its own
status; the wait/resize scripts have no handler and interruption should give 130.

| ID | PowerShell command | Bash/Zsh command | Expected result |
| --- | --- | --- | --- |
| P1 | `errlens run --terminal-mode $mode -- $runtime "$trial/name.py"` | `errlens run --terminal-mode "$mode" -- "$runtime" "$trial/name.py"` | One traceback, RU NameError card, exit 1 |
| P2 | `errlens run --terminal-mode $mode --lang en -- $runtime "$trial/name.py"` | `errlens run --terminal-mode "$mode" --lang en -- "$runtime" "$trial/name.py"` | EN Undefined name card, exit 1 |
| P3 | `errlens run --terminal-mode $mode -- $runtime "$trial/module.py"` | `errlens run --terminal-mode "$mode" -- "$runtime" "$trial/module.py"` | ModuleNotFoundError, RU card, no guessed pip install, exit 1 |
| P4 | `errlens run --terminal-mode $mode --lang en -- $runtime "$trial/syntax.py"` | `errlens run --terminal-mode "$mode" --lang en -- "$runtime" "$trial/syntax.py"` | SyntaxError, EN card, exit 1 |
| P5 | `errlens run --terminal-mode $mode -- $runtime "$trial/unicode.py"` | `errlens run --terminal-mode "$mode" -- "$runtime" "$trial/unicode.py"` | Cyrillic + globe visible, RED / Красный red if host supports ANSI, exit 0, no card |
| P6 | `errlens run --terminal-mode $mode -- $runtime "$trial/input.py"` | `errlens run --terminal-mode "$mode" -- "$runtime" "$trial/input.py"` | Enter `Андрей 🌍`; ECHO matches, exit 0, no card; inspect prompt and editing |
| P7 | `errlens run --terminal-mode $mode -- $runtime "$trial/wait.py"` | `errlens run --terminal-mode "$mode" -- "$runtime" "$trial/wait.py"` | After READY press Ctrl+C once; prompt returns, exit 130, no explanation card; normal echo/editing restored |
| P8 | `errlens run --terminal-mode $mode -- $runtime "$trial/resize.py"` | `errlens run --terminal-mode "$mode" -- "$runtime" "$trial/resize.py"` | PTY: resize physically, reported columns/lines change; Ctrl+C returns prompt. Pipe: fd 1 is a pipe, terminal-size OSError is expected |
| P9 | `errlens run --terminal-mode $mode -- $runtime "$trial/exit.py"` | `errlens run --terminal-mode "$mode" -- "$runtime" "$trial/exit.py"` | EXIT 7, status 7, no card |
| P10 | `errlens run --terminal-mode $mode -- $runtime "$trial/once.py"` | `errlens run --terminal-mode "$mode" -- "$runtime" "$trial/once.py"` | NameError + card, exit 1; executions.txt gains exactly one line, even on transport failure |
| P11 | `errlens run --terminal-mode $mode --no-explain -- $runtime "$trial/name.py"` | `errlens run --terminal-mode "$mode" --no-explain -- "$runtime" "$trial/name.py"` | Traceback and exit 1 retained; no card (repeat both modes) |
| P12 | `errlens run -- $runtime "$trial/tty.py"` then `errlens run --terminal-mode pty -- $runtime "$trial/tty.py"` | `errlens run -- "$runtime" "$trial/tty.py"` then `errlens run --terminal-mode pty -- "$runtime" "$trial/tty.py"` | Default: stdout/stderr False, inherited stdin host-dependent. PTY: all True |

Inspect P10 with `Get-Content "$trial/executions.txt"` or
`wc -l "$trial/executions.txt"`. Count increases by one per deliberate invocation;
it is not reset automatically. For P7, note the printed child PID and, after
interruption, check `Get-Process -Id <PID>` or `ps -p <PID>`: that Python process
must be gone. Report a still-running PID rather than treating prompt return as
proof of cleanup. Python traceback/KeyboardInterrupt text itself is allowed.

For both languages on every error, also repeat P3 with `--lang en`, and P4
with `--lang ru`, in each mode. For example, in PowerShell:
`errlens run --terminal-mode $mode --lang en -- $runtime "$trial/module.py"`
and `errlens run --terminal-mode $mode --lang ru -- $runtime "$trial/syntax.py"`.
In Bash/Zsh use the same flags and quote `"$mode"` and `"$runtime"` as in the table.

## Isolated shell integration (S1)

These commands install only into a newly generated temporary path, never `$PROFILE`,
`~/.bashrc` or `~/.zshrc`. Execute them manually in the disposable sessions above.
They use the existing management CLI; no permission to modify real profiles is
implied. If an existing python alias/function is preserved, record the warning
and use a fresh `-NoProfile` / clean shell before repeating.
Ensure `ERRLENS_DISABLE` is initially absent in the disposable session so the
first wrapper invocation actually exercises analysis.

PowerShell:

```powershell
$trialProfile = Join-Path $trial profile.ps1
errlens shell install powershell --profile $trialProfile
errlens shell status powershell --profile $trialProfile
. $trialProfile
python "$trial/name.py"
$LASTEXITCODE
$env:ERRLENS_DISABLE = '1'
python "$trial/name.py"
$LASTEXITCODE
Remove-Item Env:ERRLENS_DISABLE
errlens shell uninstall powershell --profile $trialProfile
Remove-Item Function:python
```

Bash/Zsh (set `shell=bash` or `shell=zsh` to match the session):

```sh
shell=bash
trialProfile="$trial/profile-$shell"
errlens shell install "$shell" --profile "$trialProfile"
errlens shell status "$shell" --profile "$trialProfile"
source "$trialProfile"
python "$trial/name.py"; echo $?
ERRLENS_DISABLE=1 python "$trial/name.py"; echo $?
errlens shell uninstall "$shell" --profile "$trialProfile"
unset -f python
```

Expect installed status, then one RU card and status 1. Disabled execution must
show the native traceback without a card, still status 1. Wrappers use pipe;
`ERRLENS_DISABLE` affects wrappers, not explicit `errlens run`. Do not infer
PowerShell `$?` from `$LASTEXITCODE`; their semantics differ. ExecutionPolicy is
never changed: record a policy refusal as BLOCKED rather than bypassing it.

## Pipe versus PTY/ConPTY

Pipe is default; it preserves separate stdout/stderr bytes and suits redirection.
Inherited input may work but prompts, buffering, colors and terminal size differ.
PTY requires actual terminal stdin/stdout. Child streams merge onto ErrLens
stdout, with echo, CRLF, cursor movement and VT conversion; binary identity is
not promised. Explanation cards still go to ErrLens stderr after restoration.
Redirected host stdin/stdout should be refused in PTY mode, never retried as pipe.
For example, `errlens run --terminal-mode pty -- python -c "print('ok')" > out.txt`
must refuse launch (run only in the temporary directory if trying this optional
check). Full-screen apps, complex grapheme rendering and arbitrary pipelines are
not acceptance guarantees. Resize the actual host window, not merely its font.

## Results

PASS (AUTO) denotes isolated automation, never a physical terminal pass. NOT
TESTED means no user interaction has been observed. Fill actual observations,
host/shell versions, mode, status and reproduction before deciding release readiness.

| Environment | Command | Expected result | Actual result | Status |
| --- | --- | --- | --- | --- |
| Windows Python 3.13.15, redirected process | `.venv\Scripts\python.exe experiments/manual_acceptance.py --check` | 12 safe pipe checks | 12 passed; temporary scripts removed | PASS (AUTO) |
| WSL Ubuntu 24.04, Python 3.12.3 | `.venv-linux/bin/python experiments/manual_acceptance.py --check` | Same 12 checks | 12 passed; temporary scripts removed | PASS (AUTO) |
| Windows, isolated native ConPTY + temporary PowerShell profiles | `.venv\Scripts\python.exe -m pytest tests/integration/test_conpty.py tests/integration/test_powershell.py -q` | Transport, input, resize, Ctrl+C, cleanup, no retry, wrapper and disable regressions pass | 29 passed | PASS (AUTO) |
| WSL, isolated POSIX PTY + temporary Bash/Zsh profiles | `.venv-linux/bin/python -m pytest tests/integration/test_pty.py tests/integration/test_posix_shell.py -q` | Transport, tty restoration, input, resize, Ctrl+C, no retry, wrappers and bypass pass | 24 passed, 1 Windows-only test skipped | PASS (AUTO) |
| Windows CLI | `python -m errlens --version` / `python -m errlens run --help` in project venv | Version 0.1.0, documented options | Confirmed | PASS (AUTO) |


| Environment | Command set | Expected result | Actual result | Status |
| --- | --- | --- | --- | --- |
| Windows Terminal / PowerShell 7 | P1 (pty/ConPTY only) | RU NameError, exit 1 | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| Windows Terminal / PowerShell 7 | P1 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| Windows Terminal / PowerShell 7 | P2 (pty/ConPTY only) | EN NameError, exit 1 | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| Windows Terminal / PowerShell 7 | P2 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| Windows Terminal / PowerShell 7 | P3 (pty/ConPTY only) | RU missing module, exit 1 | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| Windows Terminal / PowerShell 7 | P3 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| Windows Terminal / PowerShell 7 | P4 (pty/ConPTY only) | EN syntax error, exit 1 | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| Windows Terminal / PowerShell 7 | P4 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| Windows Terminal / PowerShell 7 | P5 (pty/ConPTY only) | Readable Cyrillic/emoji and ANSI colors | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| Windows Terminal / PowerShell 7 | P5 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| Windows Terminal / PowerShell 7 | P6 (pty/ConPTY only) | Interactive echo, editing and status 0 | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| Windows Terminal / PowerShell 7 | P6 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| Windows Terminal / PowerShell 7 | P7 (pty/ConPTY only) | Ctrl+C produces exit 130 | User confirms Ctrl+C and status 130; PID completion not observed | PASS (MANUAL, user-reported) |
| Windows Terminal / PowerShell 7 | P7: actual child PID and terminal restoration | Child no longer alive; normal typing restored | PID death not physically observed; automated HANDLE check is separate | NOT TESTED |
| Windows Terminal / PowerShell 7 | P7 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| Windows Terminal / PowerShell 7 | P8 (pty/ConPTY only) | PTY resize updates; pipe size OSError expected | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| Windows Terminal / PowerShell 7 | P8 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| Windows Terminal / PowerShell 7 | P9 (pty/ConPTY only) | Exit 7 without card | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| Windows Terminal / PowerShell 7 | P9 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| Windows Terminal / PowerShell 7 | P10 (pty/ConPTY only) | Marker increases exactly once | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| Windows Terminal / PowerShell 7 | P10 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| Windows Terminal / PowerShell 7 | P11 (pty/ConPTY only) | No card; traceback and status retained | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| Windows Terminal / PowerShell 7 | P11 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| Windows Terminal / PowerShell 7 | P12 (pty/ConPTY only) | ConPTY stdin/stdout/stderr are TTY | User reports successful TTY check | PASS (MANUAL, user-reported) |
| Windows Terminal / PowerShell 7 | P12 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| Windows Terminal / PowerShell 7 | S1: temporary PowerShell integration | Wrapper works in a temporary profile | User reports successful temporary integration | PASS (MANUAL, user-reported) |
| Windows Terminal / PowerShell 7 | S1: explicit ERRLENS_DISABLE=1, status and uninstall substeps | Each management/bypass substep verified | Individual substeps not explicitly reported | NOT TESTED |
| VS Code / PowerShell 7 | P1 (pty/ConPTY only) | RU NameError, exit 1 | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| VS Code / PowerShell 7 | P1 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| VS Code / PowerShell 7 | P2 (pty/ConPTY only) | EN NameError, exit 1 | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| VS Code / PowerShell 7 | P2 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| VS Code / PowerShell 7 | P3 (pty/ConPTY only) | RU missing module, exit 1 | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| VS Code / PowerShell 7 | P3 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| VS Code / PowerShell 7 | P4 (pty/ConPTY only) | EN syntax error, exit 1 | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| VS Code / PowerShell 7 | P4 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| VS Code / PowerShell 7 | P5 (pty/ConPTY only) | Readable Cyrillic/emoji and ANSI colors | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| VS Code / PowerShell 7 | P5 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| VS Code / PowerShell 7 | P6 (pty/ConPTY only) | Interactive echo, editing and status 0 | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| VS Code / PowerShell 7 | P6 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| VS Code / PowerShell 7 | P7 (pty/ConPTY only) | Ctrl+C produces exit 130 | User confirms Ctrl+C and status 130; PID completion not observed | PASS (MANUAL, user-reported) |
| VS Code / PowerShell 7 | P7: actual child PID and terminal restoration | Child no longer alive; normal typing restored | PID death not physically observed; automated HANDLE check is separate | NOT TESTED |
| VS Code / PowerShell 7 | P7 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| VS Code / PowerShell 7 | P8 (pty/ConPTY only) | PTY resize updates; pipe size OSError expected | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| VS Code / PowerShell 7 | P8 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| VS Code / PowerShell 7 | P9 (pty/ConPTY only) | Exit 7 without card | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| VS Code / PowerShell 7 | P9 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| VS Code / PowerShell 7 | P10 (pty/ConPTY only) | Marker increases exactly once | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| VS Code / PowerShell 7 | P10 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| VS Code / PowerShell 7 | P11 (pty/ConPTY only) | No card; traceback and status retained | User reports this scenario passed in ConPTY; exact host versions not supplied | PASS (MANUAL, user-reported) |
| VS Code / PowerShell 7 | P11 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| VS Code / PowerShell 7 | P12 (pty/ConPTY only) | ConPTY stdin/stdout/stderr are TTY | User reports successful TTY check | PASS (MANUAL, user-reported) |
| VS Code / PowerShell 7 | P12 (pipe/default comparison) | Original pipe expectation above | No explicit manual pipe result supplied | NOT TESTED |
| VS Code / PowerShell 7 | S1: temporary PowerShell integration | Wrapper works in a temporary profile | User reports successful temporary integration | PASS (MANUAL, user-reported) |
| VS Code / PowerShell 7 | S1: explicit ERRLENS_DISABLE=1, status and uninstall substeps | Each management/bypass substep verified | Individual substeps not explicitly reported | NOT TESTED |
| Windows Terminal / WSL Bash | P1 (pipe and pty) | RU NameError explanation | Confirmed in both modes; codes 0/1/7 also reported | PASS (MANUAL, user-reported) |
| Windows Terminal / WSL Bash | P2 (pipe and pty), exact commands above | EN NameError, exit 1 | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Bash | P3 (pipe and pty), exact commands above | RU missing module, exit 1 | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Bash | P4 (pipe and pty), exact commands above | EN syntax error, exit 1 | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Bash | P5 (mode not individually specified) | Cyrillic/Unicode and ANSI colors | User confirms readable text and colors; per-mode observations not supplied | PASS (MANUAL, user-reported) |
| Windows Terminal / WSL Bash | P6 (mode not individually specified) | Interactive input works | Confirmed; line-editing details not separately reported | PASS (MANUAL, user-reported) |
| Windows Terminal / WSL Bash | P7: Ctrl+C (mode not individually specified) | Interrupt returns 130 | User confirms status 130 | PASS (MANUAL, user-reported) |
| Windows Terminal / WSL Bash | P7: physical child PID / mode restoration | Child gone; normal input restored | Not explicitly observed; automated PID evidence remains separate | NOT TESTED |
| Windows Terminal / WSL Bash | P8: PTY resize | Reported terminal dimensions change | Confirmed | PASS (MANUAL, user-reported) |
| Windows Terminal / WSL Bash | P8: pipe size limitation | Documented size OSError in pipe | Not explicitly reported | NOT TESTED |
| Windows Terminal / WSL Bash | P9: exit code | Exit status preserved | 0, 1, 7 confirmed | PASS (MANUAL, user-reported) |
| Windows Terminal / WSL Bash | P10 (pipe and pty), exact commands above | Marker increases exactly once | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Bash | P11 (pipe and pty), exact commands above | No card; traceback and status retained | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Bash | P12, exact commands above | Default pipe vs explicit terminal isatty values | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Bash | S1, exact commands above | Temporary wrapper install/status, explain, disable, uninstall | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Zsh | P1 (pipe and pty), exact commands above | RU NameError, exit 1 | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Zsh | P2 (pipe and pty), exact commands above | EN NameError, exit 1 | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Zsh | P3 (pipe and pty), exact commands above | RU missing module, exit 1 | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Zsh | P4 (pipe and pty), exact commands above | EN syntax error, exit 1 | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Zsh | P5: Unicode (pty) | Readable Unicode | Confirmed in PTY | PASS (MANUAL, user-reported) |
| Windows Terminal / WSL Zsh | P5: ANSI colors | Correct colors | Not explicitly reported | NOT TESTED |
| Windows Terminal / WSL Zsh | P6 (pty) | Interactive input works | Confirmed; line-editing details not separately reported | PASS (MANUAL, user-reported) |
| Windows Terminal / WSL Zsh | P7: Ctrl+C (pty) | Interrupt returns 130 | User confirms status 130 | PASS (MANUAL, user-reported) |
| Windows Terminal / WSL Zsh | P7: physical child PID / mode restoration | Child gone; normal input restored | Not explicitly observed; automated PID evidence remains separate | NOT TESTED |
| Windows Terminal / WSL Zsh | P8: PTY resize | Reported terminal dimensions change | Confirmed | PASS (MANUAL, user-reported) |
| Windows Terminal / WSL Zsh | P8: pipe size limitation | Documented size OSError in pipe | Not explicitly reported | NOT TESTED |
| Windows Terminal / WSL Zsh | P9: exit code | Exit status preserved | 7 confirmed; 0/1 not separately enumerated | PASS (MANUAL, user-reported) |
| Windows Terminal / WSL Zsh | P10 (pipe and pty), exact commands above | Marker increases exactly once | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Zsh | P11 (pipe and pty), exact commands above | No card; traceback and status retained | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Zsh | P12, exact commands above | Default pipe vs explicit terminal isatty values | No physical-host observation | NOT TESTED |
| Windows Terminal / WSL Zsh | S1: install/status/explain/disable | Zsh management and wrapper bypass work | All four reported successful; profile path not supplied | PASS (MANUAL, user-reported) |
| Windows Terminal / WSL Zsh | S1: uninstall/status after removal | Removal and not installed status | Not reported | NOT TESTED |
| VS Code WSL / Bash | P1: NameError (pipe and pty) | NameError detection/explanation | Confirmed; language not explicitly specified | PASS (MANUAL, user-reported) |
| VS Code WSL / Bash | P1: explicit RU language | RU card | Language not explicitly reported | NOT TESTED |
| VS Code WSL / Bash | P2 (pipe and pty), exact commands above | EN NameError, exit 1 | No physical-host observation | NOT TESTED |
| VS Code WSL / Bash | P3 (pipe and pty), exact commands above | RU missing module, exit 1 | No physical-host observation | NOT TESTED |
| VS Code WSL / Bash | P4 (pipe and pty), exact commands above | EN syntax error, exit 1 | No physical-host observation | NOT TESTED |
| VS Code WSL / Bash | P5 (pipe and pty) | Cyrillic/Unicode and ANSI colors | User explicitly confirms these features for pipe/PTY | PASS (MANUAL, user-reported) |
| VS Code WSL / Bash | P6 (pipe and pty) | Interactive input works | User explicitly confirms input for pipe/PTY; editing details not separately reported | PASS (MANUAL, user-reported) |
| VS Code WSL / Bash | P7: Ctrl+C (mode not individually specified) | Interrupt returns 130 | User confirms status 130 | PASS (MANUAL, user-reported) |
| VS Code WSL / Bash | P7: physical child PID / mode restoration | Child gone; normal input restored | Not explicitly observed; automated PID evidence remains separate | NOT TESTED |
| VS Code WSL / Bash | P8: PTY resize | Reported terminal dimensions change | Confirmed | PASS (MANUAL, user-reported) |
| VS Code WSL / Bash | P8: pipe size limitation | Documented size OSError in pipe | Not explicitly reported | NOT TESTED |
| VS Code WSL / Bash | P9: exit code | Exit status preserved | 7 confirmed; 0/1 not separately enumerated | PASS (MANUAL, user-reported) |
| VS Code WSL / Bash | P10 (pipe and pty), exact commands above | Marker increases exactly once | No physical-host observation | NOT TESTED |
| VS Code WSL / Bash | P11 (pipe and pty), exact commands above | No card; traceback and status retained | No physical-host observation | NOT TESTED |
| VS Code WSL / Bash | P12, exact commands above | Default pipe vs explicit terminal isatty values | No physical-host observation | NOT TESTED |
| VS Code WSL / Bash | S1: install/status/explain/disable/uninstall/status | Wrapper works, bypass works, removal yields not installed | All explicitly confirmed; profile path not supplied | PASS (MANUAL, user-reported) |
| VS Code WSL / Zsh | P1 (pipe and pty), exact commands above | RU NameError, exit 1 | No physical-host observation | NOT TESTED |
| VS Code WSL / Zsh | P2 (pipe and pty), exact commands above | EN NameError, exit 1 | No physical-host observation | NOT TESTED |
| VS Code WSL / Zsh | P3 (pipe and pty), exact commands above | RU missing module, exit 1 | No physical-host observation | NOT TESTED |
| VS Code WSL / Zsh | P4 (pipe and pty), exact commands above | EN syntax error, exit 1 | No physical-host observation | NOT TESTED |
| VS Code WSL / Zsh | P5 (pipe and pty), exact commands above | Readable Cyrillic/emoji and ANSI colors | No physical-host observation | NOT TESTED |
| VS Code WSL / Zsh | P6 (pipe and pty), exact commands above | Interactive echo, editing and status 0 | No physical-host observation | NOT TESTED |
| VS Code WSL / Zsh | P7 (pipe and pty), exact commands above | Ctrl+C, status 130, PID gone, modes restored | No physical-host observation | NOT TESTED |
| VS Code WSL / Zsh | P8 (pipe and pty), exact commands above | PTY resize updates; pipe size OSError expected | No physical-host observation | NOT TESTED |
| VS Code WSL / Zsh | P9 (pipe and pty), exact commands above | Exit 7 without card | No physical-host observation | NOT TESTED |
| VS Code WSL / Zsh | P10 (pipe and pty), exact commands above | Marker increases exactly once | No physical-host observation | NOT TESTED |
| VS Code WSL / Zsh | P11 (pipe and pty), exact commands above | No card; traceback and status retained | No physical-host observation | NOT TESTED |
| VS Code WSL / Zsh | P12, exact commands above | Default pipe vs explicit terminal isatty values | No physical-host observation | NOT TESTED |
| VS Code WSL / Zsh | S1, exact commands above | Temporary wrapper install/status, explain, disable, uninstall | No physical-host observation | NOT TESTED |


No product defect was found in the automated checks performed in this stage.
Windows ConPTY manual PASS entries are the user's observations, not agent-operated
terminal sessions. The report covers the named features; exact host versions,
pipe comparisons and individual integration bypass/removal substeps were not
provided and are not inferred. Windows PID completion is verified automatically
separately; that does not turn the physical PID row into a manual PASS.
That statement does not cover the unobserved physical-host rows above. Record
any failure with command ID, mode, shell/host version, exit status, exact output
and reproducible steps. Keep NOT TESTED until actually observed; use FAIL for a
reproducible discrepancy and BLOCKED for missing host/access/policy. Do not mark
manual checks PASS until observed. Unfilled rows are coverage gaps, not automatic
release blockers; apply the release-critical assessment below.

## Optional remaining WSL checks: copy-ready commands

Run these separately in Windows Terminal's Ubuntu 24.04 tab and VS Code's WSL
Ubuntu 24.04 integrated terminal, for both shells (four sessions total). Enter
`bash --noprofile --norc` for Bash, or `zsh -f` for Zsh. Then paste the shared
setup and diagnostic block below. It creates only a fresh temporary directory.
Do not use the Windows Python/venv inside WSL.

```sh
cd /mnt/d/Projects/ErrLens
source .venv-linux/bin/activate
runtime="$PWD/.venv-linux/bin/python"
trial=$("$runtime" experiments/manual_acceptance.py)
unset ERRLENS_DISABLE
printf 'Temporary scripts: %s\n' "$trial"
errlens --version
for mode in pipe pty; do
  for lang in ru en; do
    for script in name module syntax; do
      errlens run --terminal-mode "$mode" --lang "$lang" -- "$runtime" "$trial/$script.py"
      printf 'Expected 1; actual %s\n' "$?"
    done
  done
  errlens run --terminal-mode "$mode" -- "$runtime" "$trial/unicode.py"
  printf 'Expected 0; actual %s\n' "$?"
  errlens run --terminal-mode "$mode" -- "$runtime" "$trial/exit.py"
  printf 'Expected 7; actual %s\n' "$?"
  errlens run --terminal-mode "$mode" --no-explain -- "$runtime" "$trial/name.py"
  printf 'Expected 1, no card; actual %s\n' "$?"
  errlens run --terminal-mode "$mode" -- "$runtime" "$trial/once.py"
  printf 'Expected 1; actual %s\n' "$?"
  wc -l "$trial/executions.txt"
done
errlens run -- "$runtime" "$trial/tty.py"
errlens run --terminal-mode pty -- "$runtime" "$trial/tty.py"
```

Expect a full explanation in each selected language for all three errors,
readable Cyrillic/emoji, red ANSI text, no card on success or --no-explain.
The marker counts must be 1 and 2, respectively. Default pipe stdout/stderr
are not TTY; all three streams are TTY in explicit pty mode.

For interaction, paste one command at a time; type `Андрей 🌍` at each input
prompt. After each wait command prints READY, press Ctrl+C once, then paste
the next status command. Do not interrupt the shell setup or an entire pasted
block. Report the printed real child PID, not the shell's `$$`.

```sh
errlens run --terminal-mode pipe -- "$runtime" "$trial/input.py"
echo $?
errlens run --terminal-mode pty -- "$runtime" "$trial/input.py"
echo $?
errlens run --terminal-mode pipe -- "$runtime" "$trial/wait.py"
```

After Ctrl+C:

```sh
echo $?  # expected 130
errlens run --terminal-mode pty -- "$runtime" "$trial/wait.py"
```

After Ctrl+C:

```sh
echo $?  # expected 130
errlens run --terminal-mode pty -- "$runtime" "$trial/resize.py"
```

Resize the real window (both narrower/wider and shorter/taller), observe changed
columns/lines, then Ctrl+C. Check `echo $?` (130), normal typing and echo. The
identity-safe automated PID checks below already prove process exit in isolated
transports; these physical keyboard/host checks remain manual and NOT TESTED.

Finally test integration without changing a real profile:

```sh
if [ -n "${ZSH_VERSION-}" ]; then shell=zsh; else shell=bash; fi
trialProfile="$trial/profile-$shell"
errlens shell install "$shell" --profile "$trialProfile"
errlens shell status "$shell" --profile "$trialProfile"
source "$trialProfile"
python "$trial/name.py"
echo $?  # 1; RU explanation present
ERRLENS_DISABLE=1 python "$trial/name.py"
echo $?  # 1; traceback present, no ErrLens card
errlens shell uninstall "$shell" --profile "$trialProfile"
unset -f python
```

Send results for all four sessions: host/shell versions, mode, error languages,
input/colors/resize/Ctrl+C behavior, exit codes, marker counts and integration
disable/uninstall. Record failures verbatim. No physical WSL row becomes PASS
from automated results alone. The latest user-reported updates below supersede
the original all-NOT-TESTED state, without broadening the reported scope.

## Latest automated completion evidence

These results supplement, and do not replace, the manual table. PID numbers
below identify the completed test runs only; do not reuse them as manual targets.

| Environment | Command | Expected result | Actual result | Status |
| --- | --- | --- | --- | --- |
| WSL Python 3.12.3 | `.venv-linux/bin/python experiments/manual_acceptance.py --check` | 12 safe pipe checks | 12 passed again | PASS (AUTO) |
| WSL Ubuntu 24.04, Bash/Zsh profiles and POSIX transports | `.venv-linux/bin/python -m pytest tests/integration/test_interrupt_pid.py tests/integration/test_pty.py tests/integration/test_posix_shell.py -q -rP` | Existing assertions plus identity-safe PID exit checks pass | 26 passed, 1 Windows-only test skipped | PASS (AUTO) |
| Windows pipe / ConPTY | `.venv/Scripts/python.exe -m pytest tests/integration/test_interrupt_pid.py -q -rP` | Real child alive before Ctrl+C, same process terminated afterward; CLI status 130 | 2 passed; PID 7296 (pipe), 23980 (ConPTY) confirmed exited | PASS (AUTO) |
| WSL pipe / POSIX PTY | `.venv-linux/bin/python -m pytest tests/integration/test_interrupt_pid.py -q -rP` | Same real-process exit check | 2 passed; PID 644 (pipe), 649 (PTY) confirmed exited | PASS (AUTO) |

The child prints a unique per-run token with its own `os.getpid()`. The probe
acquires a Windows process HANDLE or Linux pidfd while that child is still alive,
asserts it has not exited, then injects Ctrl+C into the nested console/PTY (POSIX
pipe uses SIGINT to ErrLens). After CLI completion, it waits on the same pinned
process identity. A missing PID, early exit, CLI status other than 130 or surviving
child fails the test. Failure-path forced cleanup cannot produce a PASS. Each
probe is isolated with an outer timeout. The identity-specific test requires
Windows HANDLEs or Linux pidfds; it is not a claim about physical-host behavior
or a new macOS PID test. Existing macOS transport assertions are unchanged.

No confirmed blocking product defect was discovered. Remaining acceptance gaps:
remaining WSL scenarios listed in the latest update, Windows manual pipe comparison, explicit PowerShell
disable/status/uninstall substeps if not already checked, and physical PID/mode
observations if required for host sign-off. No production source, version, real
profile, release, tag, commit or push was changed in this continuation.

## Latest user evidence and remaining checks (2026-11-10)

Only `docs/manual-acceptance.md` was edited for this evidence update. No tests
were rerun for a documentation-only change; automated results above are earlier
evidence, not new manual observations. PASS entries are explicitly user-reported.
No new product defect is confirmed. The later release-critical assessment
classifies these remaining observations; repeating this checklist is optional.

| Environment | Command/scenario | Expected result | Actual result | Status |
| --- | --- | --- | --- | --- |
| Windows Terminal / WSL Zsh | Python errors through PTY and wrapper | An error produces an explanation | User confirms errors work, but does not enumerate types/languages | PASS (MANUAL, generic scope only) |
| Windows Terminal / WSL Zsh | Earlier prompt observation | No literal prompt escapes | Literal escapes were previously observed; cause not established | FAIL (historical observation) |
| Windows Terminal / WSL Zsh | Fresh clean Zsh prompt | Normal prompt | User confirms normal prompt in clean Zsh | PASS (MANUAL, user-reported) |
| Windows Terminal / WSL Zsh | Reproduce and attribute earlier prompt issue | Identify actual cause if reproducible | Not reproduced or attributed by this update; inherited Bash prompt is only a hypothesis for this incident | NOT TESTED |

Do not infer that the historical prompt failure is an ErrLens defect, or that
its root cause has been fixed. The earlier isolated prompt test demonstrates a
possible mechanism, not the cause of the user's particular observation. If the
problem returns, report the shell launch/activation sequence and shell versions;
do not send a complete environment dump or unrelated configuration/secrets.

Remaining scope:

- **Windows Terminal / WSL Bash:** EN NameError, ModuleNotFoundError/SyntaxError
  in both languages, no-explain, exactly-once marker, TTY comparison and isolated
  integration/bypass/removal. Per-mode Unicode/input/Ctrl+C details were not
  enumerated; report those when running the remaining pipe/PTY checks.
- **Windows Terminal / WSL Zsh:** explicit error types/languages, pipe comparison,
  ANSI colors, no-explain, marker and TTY; uninstall followed by not-installed
  status. PTY Unicode/input/resize/Ctrl+C/exit 7 already passed.
- **VS Code / WSL Bash:** explicitly selected RU/EN errors, missing module and
  syntax error, no-explain, marker and TTY. Integration including disable,
  uninstall and not-installed status is already confirmed; do not repeat it
  solely to satisfy an old table row.
- **VS Code / WSL Zsh:** full remaining-WSL command set from the preceding section,
  including interactive checks and temporary integration. No result was supplied.
- **Windows PowerShell hosts:** original pipe comparison and separately reported
  disable/status/uninstall substeps remain unconfirmed in their existing rows.
- Physical child-PID/mode-restoration observations remain NOT TESTED; identity-safe
  automated HANDLE/pidfd exit checks are PASS (AUTO), not manual sign-off.

### Optional short common WSL remainder block

In each of the first three WSL sessions, use a clean Bash/Zsh session and paste
this block. A few already-passed NameError cases repeat to keep the command set
small; report the selected language and mode. This makes fresh temporary scripts
and does not load or modify any real profile.

```sh
cd /mnt/d/Projects/ErrLens
source .venv-linux/bin/activate
runtime="$PWD/.venv-linux/bin/python"
trial=$("$runtime" experiments/manual_acceptance.py)
unset ERRLENS_DISABLE
for mode in pipe pty; do
  for lang in ru en; do
    for script in name module syntax; do
      errlens run --terminal-mode "$mode" --lang "$lang" -- "$runtime" "$trial/$script.py"
      printf 'Expected 1; actual %s\n' "$?"
    done
  done
  errlens run --terminal-mode "$mode" --no-explain -- "$runtime" "$trial/name.py"
  printf 'Expected 1 without card; actual %s\n' "$?"
  errlens run --terminal-mode "$mode" -- "$runtime" "$trial/once.py"
  printf 'Expected 1; actual %s\n' "$?"
  wc -l "$trial/executions.txt"
done
errlens run -- "$runtime" "$trial/tty.py"
errlens run --terminal-mode pty -- "$runtime" "$trial/tty.py"
```

Expect full RU/EN cards for each error, no card for --no-explain, marker counts
1 then 2, and default stdout/stderr False versus all three True in PTY.
For Zsh also run the following one command at a time, using the same variables:

```sh
errlens run --terminal-mode pipe -- "$runtime" "$trial/unicode.py"
errlens run --terminal-mode pty -- "$runtime" "$trial/unicode.py"
errlens run --terminal-mode pipe -- "$runtime" "$trial/input.py"
errlens run --terminal-mode pipe -- "$runtime" "$trial/wait.py"
```

Enter `Андрей 🌍` for input; after READY in wait.py press Ctrl+C and immediately
run `echo $?` (130). Check normal input/echo after returning. For Windows Terminal
Bash, and Zsh removal, finish the isolated S1 workflow (no real profile path):

```sh
if [ -n "${ZSH_VERSION-}" ]; then shell=zsh; else shell=bash; fi
trialProfile="$trial/profile-$shell"
errlens shell install "$shell" --profile "$trialProfile"
errlens shell status "$shell" --profile "$trialProfile"
source "$trialProfile"
python "$trial/name.py"
echo $?  # 1, card present
ERRLENS_DISABLE=1 python "$trial/name.py"
echo $?  # 1, no card
errlens shell uninstall "$shell" --profile "$trialProfile"
errlens shell status "$shell" --profile "$trialProfile"
unset -f python
```

The final status must contain `not installed`. For VS Code WSL Zsh use the full
interactive block above as well (PTY input, Ctrl+C and physical resize). Send
results per host/shell/mode; remaining rows stay NOT TESTED until reported.

## Release-critical assessment (2026-11-10)

**READY for release preparation. Stage 7.3 accepted with documented limits.**
This supersedes the earlier assumption that every host/shell/language/mode table
cell must be manually completed. It changes no PASS/FAIL/NOT TESTED observation.
No additional manual run is required to address a currently confirmed blocker.

Read-only verification of [Actions #6](https://github.com/ErrLens/errlens-cli/actions/runs/42625948427)
confirmed success for all 11 jobs at
`84dbb9c927b1b0eaf3ac6efc50863b9f0ef72836`: Windows, Ubuntu and macOS on Python
3.11–3.13 plus Windows/Ubuntu packaging. The later PID test and acceptance helper
are local, uncommitted evidence, not part of that CI run. Production code has
not changed since the green baseline. No tests were rerun for this assessment.

### Critical properties and sufficient existing evidence

| Release-critical property | Existing evidence | Assessment |
| --- | --- | --- |
| Pipe default, bytes and child status preserved | CI `test_execution.py`, `test_vt_forwarding.py`, user pipe results on WSL; immutable-capture regressions | Covered; no confirmed blocker |
| Full explanations and policy (RU/EN, errors, success, --no-explain) | CI analyzer/rule/CLI tests, recorded Actions #5 fixtures; 12 safe pipe checks on each local OS; user Windows and WSL error reports | Covered; manually repeating each language/error in every host is optional |
| Interactive input, Unicode/ANSI, resize and Ctrl+C | Real isolated PTY/ConPTY tests in CI; manual Windows Terminal/VS Code ConPTY and WSL Bash/Zsh observations | Covered for 0.1.0 scope; not a claim of every physical host combination |
| Real child exits, cleanup and terminal restoration | Local identity-safe HANDLE/pidfd tests confirm alive-before-interrupt and exited-after-interrupt for pipe and terminal modes; CI checks terminal restoration, handles/fds and descendant cleanup | Covered automatically; physical PID rows remain NOT TESTED without blocking preparation |
| Bounded capture/normalization, no transport retry | CI capture/VT limit tests, transport failure marker and cleanup assertions; manual once check on Windows | Covered; no evidence of repeated execution or unbounded CSI expansion |
| Safe shell install/removal and disable | CI PowerShell/Bash/Zsh temporary-profile roundtrips, management CLI, bypass tests; local shell suites; user Zsh install/disable and VS Code Bash uninstall/not-installed | Covered; repeating the same profile operations in each terminal host is optional |
| Installable package with required resources/helpers | Both CI packaging jobs build wheel/sdist, install wheel in separate environments and run tests; prior local outside-checkout wheel checks | Covered at green baseline; final artifact verification belongs to normal release preparation |

Critical gaps would be a reproducible child left alive after cleanup, corrupted
pipe bytes/status, repeated command execution, destructive profile handling,
unbounded resource expansion or a supported ordinary traceback no longer being
explained. No such unresolved defect is confirmed by current evidence. If one
appears, reproduce only that exact scenario with mode/host/version, retain its
output and stop release preparation until triaged; do not rerun the entire matrix
merely to fill cells.

### Remaining NOT TESTED: nonblocking manual extensions

- VS Code WSL Zsh: an unobserved host/shell combination. Zsh integration is
  independently covered by automation and Windows Terminal manual results;
  VS Code WSL transport is manually covered with Bash. This composition is
  reasonable release evidence, **not a manual PASS for VS Code Zsh**.
- Explicit RU/EN and all three errors, no-explain, exactly-once markers and TTY
  comparisons repeated in every physical session: shared analyzer/CLI logic is
  already exercised automatically and sampled manually. These add coverage,
  rather than resolve a known blocker.
- Windows manual pipe comparisons, repeated PowerShell management/bypass
  substeps, Zsh uninstall/status and WT Bash integration: existing native shell
  and profile tests cover the logic, with additional manual results on other
  sessions. All unobserved physical rows retain NOT TESTED.
- Physical PID and detailed post-interrupt editing observations: optional
  corroboration of real-process and mode-restoration automated checks.
- Historical Zsh literal prompt escapes: retain the historical FAIL and unknown
  cause. Clean Zsh was manually successful; there is no reproducible current
  ErrLens defect. This does not establish that Bash prompt inheritance caused
  the particular incident. If it returns in a clean session, collect the precise
  launch/activation sequence and compare native Python versus the wrapper in
  that same session; investigate that one reproduction.

Limits carried into release preparation: terminal output is merged UTF-8/VT,
not byte-identical binary streams; redirected host stdin/stdout require pipe;
complex screen redraws/graphemes, arbitrary full-screen apps and transparent
shell pipelines are not guaranteed. Windows 10/other architectures and physical
macOS hosts have not been locally qualified; the CI matrix does not turn them
into manual PASS. Keep claims scoped to the documented, tested behavior.

### Next action

The maintainer has accepted closing stage 7.3; move to release preparation;
no repeated acceptance checklist is required. The three currently untracked
acceptance files (this document, the temporary-script helper and the PID test)
still need the ordinary review/inclusion decision before committing a release
candidate. That is repository preparation, not a confirmed product defect.
Any resulting candidate commit/artifact should receive its normal CI/build
verification. Publication, tags, commits and pushes require separate permission.
