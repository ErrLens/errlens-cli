# ErrLens

ErrLens is a local, open-source CLI that adds readable Russian or English explanations to recognized Python errors. It helps developers understand tracebacks without copying them to an external service. Explanations are rule-based and work offline after installation; no API key or AI model is required.

ErrLens runs a command through `errlens run`. Its default pipe mode forwards the original stdout and stderr, then appends an explanation to stderr when an error is recognized. Optional shell wrappers intercept only `python`; explicit terminal mode uses merged terminal output.

## Requirements and installation

Python 3.11 or newer is required. On Windows, Linux or macOS, install from a local checkout:

```console
python -m pip install .
```

For development, use a virtual environment and install `python -m pip install -e ".[dev]"`. Installing dependencies requires an available package index or local wheels.

The PyPI distribution name is **errlens-cli**; the Python import and executable
are both **errlens**. This candidate has not been uploaded. After publication,
install with `python -m pip install errlens-cli==0.1.0`, then run `errlens --version`.
Until then use this checkout or a verified supplied wheel:
`python -m pip install /path/to/errlens_cli-0.1.0-py3-none-any.whl`.
The existing PyPI package named `errlens` is not the distribution selected for
this repository. See [release preparation](https://github.com/ErrLens/errlens-cli/blob/main/docs/releasing.md).
CI covers CPython 3.11–3.13; newer Python versions are not yet qualified.

## Usage

```console
errlens --help
errlens --version
errlens run python main.py
errlens run --lang en -- python main.py
errlens run --no-explain -- python main.py
errlens run python -c "print(undefined_variable)"
```

Russian is the default; `--lang en` selects English. Place ErrLens options before the executable; arguments after the executable belong to the child process. `--no-explain` skips analysis. The optional `--` makes the boundary explicit.

The original traceback remains visible. For example, a `NameError` can be followed by an explanation that the name is unavailable in the current scope and suggestions to check its spelling and definition. Causes are described as possibilities, not established facts. Successful commands and nonzero exits without recognized diagnostics do not produce an explanation.

## Supported diagnostics

Rules cover `ModuleNotFoundError`, `ImportError`, `SyntaxError`, `IndentationError`, `TabError`, `NameError`, `TypeError`, `AttributeError`, `KeyError`, `FileNotFoundError` and `PermissionError`. Other structured exceptions receive a neutral notice. Incomplete diagnostics are marked as such; `ExceptionGroup` is summarized at its outer level. For a chain of exceptions, the final diagnostic is explained and linked predecessors are noted.

Suggested commands are never executed. A pip command is shown only for the exact `requests` import and an explicitly specified absolute Python executable path, with a condition to confirm that the distribution is actually needed in that environment. Import names do not generally identify package names, and a missing module may be local.

## Behavior and limitations

- ErrLens launches argument sequences without `shell=True`. Shell pipelines and builtins are interpreted by the invoking shell, not by ErrLens. On Windows, the operating system may invoke a command interpreter for `.bat` or `.cmd` files even with `shell=False`.
- Separate bounded buffers retain up to 1 MiB per stream for analysis. Original bytes are forwarded as they arrive; the diagnostic copy may be truncated. No output logs are saved to disk.
- Pipes change `isatty()` and may affect child buffering and colors. Interactive programs, job control and full-screen applications are not guaranteed to work. The relative ordering of stdout and stderr cannot be reconstructed.
- The child exit code is preserved for normal exits. On POSIX, signal termination becomes `128 + signal`; user interruption returns 130. Runner failures have their own codes: 125 for internal failures, 126 for permission errors, 127 for missing executables and 141 for broken pipes. Child programs can also use these codes; ErrLens identifies its own failures in stderr when possible.
- In pipe mode, Ctrl+C handling uses a separate process group. Windows pipe cleanup does not guarantee termination of an arbitrary descendant tree. After the child exits, pipes held open by descendants are subject to a one-second drain timeout. ConPTY uses the Job Object cleanup described below.
- Recognition targets standard CPython traceback formatting; IPython/Jupyter and logger-prefixed tracebacks are not supported. A traceback-like log can be ambiguous. Stdout diagnostics require a failed Python command. Unknown or incomplete data is not presented as a certain cause.
- Rich markup and terminal control characters from diagnostic data are rendered literally or escaped in the ErrLens block. Redirected explanations are plain text without ANSI. Original child output is not sanitized.
- Explanation fields are capped at 2,048 characters; linked exception messages at 256 characters. The forwarded traceback is not shortened by this limit.
- ErrLens does not fix code, install packages, collect telemetry or contact a service. Shell wrappers and terminal mode are explicit opt-ins; VS Code extension support remains future work.

## Opt-in PowerShell 7 integration (Windows)

```powershell
errlens shell install powershell
errlens shell status powershell
errlens shell uninstall powershell
```

Installation explicitly edits the current user's **all-hosts PowerShell 7 profile**
(shared with VS Code), discovered using `pwsh -NoProfile`. Restart PowerShell after
installation/removal. ExecutionPolicy is never changed; your policy must allow
loading the profile and the integration script. No administrator access is needed.
For an isolated trial or a custom host profile use `--profile 'path/to/profile.ps1'`
on each management command, then dot-source that profile manually.

An owned script is placed in an `ErrLens` subdirectory next to the selected profile.
Only one guarded dot-source line is appended. Existing profile bytes are preserved;
each modification of an existing profile creates a uniquely named backup alongside
it. Backups are retained on removal. Edited connection lines and unowned integration
files are refused rather than overwritten. A newly created profile is left empty
after removal. Existing `python` aliases/functions are preserved with a warning.

After loading, plain `python main.py`, `python -c "print(undefined_variable)"` and
`python --version` delegate to `errlens run`. Only the command name `python` is
wrapped. Absolute executable paths, `py`, pip and other commands bypass it.
The native Python application is resolved from PATH on every invocation, so venv
activation is respected. The ErrLens runtime is bound to the absolute Python path
used during installation; `errlens` need not be in PATH. Keep that environment
installed. To migrate it, uninstall the integration and reinstall from the new runtime.

Temporarily bypass analysis with `$env:ERRLENS_DISABLE='1'`; restore it with
`Remove-Item Env:ERRLENS_DISABLE`. To remove the wrapper from the current session,
use `Remove-Item Function:python`. Persistent removal takes effect in new sessions.

This is a PowerShell function calling a native program, not transparent terminal
capture. `$LASTEXITCODE` is explicitly propagated. `$?` may report function success
even when Python fails; inspect `$LASTEXITCODE`. PowerShell 7.3+ uses Standard
native argument passing locally inside the wrapper; 7.0–7.2 retain their legacy
quoting/empty-argument limitations. Global preferences are not changed.
Pipeline output and `>` pass through PowerShell's object/text conversion and do
not guarantee byte identity (including PowerShell 7.4 native redirection behavior).
Pipeline input is not forwarded by this wrapper. Avoid binary pipelines, REPLs,
interactive and full-screen applications; use an absolute Python executable when
native semantics are needed. ExecutionPolicy, host-specific profile loading and
VS Code itself require manual verification on the target machine.

## Opt-in Bash and Zsh integration

On Linux/macOS, explicitly install with `errlens shell install bash` or
`errlens shell install zsh`; use `status` or `uninstall` in place of `install`.
Bash uses `~/.bashrc`; Zsh uses `${ZDOTDIR:-$HOME}/.zshrc`. Bash login shells
do not necessarily load `.bashrc`: configure your login profile to source it
yourself if needed. These are interactive startup files; noninteractive shells
do not automatically load them. `--profile PATH` selects an isolated/custom file.

An owned script in `.errlens` beside the profile is sourced by one guarded line.
Existing profile bytes are retained, changes receive unique backups, repeated
installation is idempotent, and removal removes only the exact owned line and script.
Edited lines and unowned scripts are refused. Backups remain after removal.
Existing `python` functions and aliases take precedence and are preserved.

The `python` function resolves the external interpreter and `errlens` on each
invocation, forwards `"$@"`, working directory and exit status, and respects an
activated virtual environment. `ERRLENS_DISABLE=1 python ...` bypasses analysis;
if ErrLens is absent from PATH, the native Python is run directly. Use `unset -f
python` to disable the wrapper in the current shell. `command python`, an absolute
path, `python3`, pip and other commands bypass it. Restart or source the profile
after installation; restart or unset the function after uninstallation.

When starting Zsh from Bash with an active virtual environment, the Bash
activation script may have modified and exported prompt variables. Bash prompt
escapes are not Zsh prompt syntax and may appear literally. Start a clean Zsh,
then run `source /path/to/venv/bin/activate` within Zsh. The ErrLens integration
does not change `PS1` or `PROMPT`; your Zsh configuration can define its own prompt.
Manual reports of Windows 11/PowerShell and Ubuntu 24.04/WSL Bash and Zsh are
distinct from the automated CI checks; consult CI results for verified runs.

Redirection and pipelines follow the shell and `errlens run` pipe semantics.
Input is inherited, but interactive/terminal-dependent programs and exact stdout/
stderr interleaving are not guaranteed. Ctrl+C follows Runner process-group handling;
PTY and job-control equivalence are not guaranteed. Paths with spaces and Unicode
are quoted without `eval`. No system profiles or shell settings are modified.

## Explicit terminal mode

Use `errlens run --terminal-mode pty -- python script.py` when terminal stdin
and stdout are available. Linux/macOS use POSIX PTY; Windows 10 1809+ and Windows
11 use native ConPTY. Pipe remains the default, including all shell wrappers.
A transport error never triggers an automatic second run. Windows requires
actual console handles and a native executable (.exe or .com), with no batch
file or legacy winpty fallback. No extra runtime dependency or compiler is needed.

Terminal mode supplies a terminal, input, window-size propagation and terminal
Ctrl+C handling. stdout and stderr merge onto ErrLens stdout; echo and LF-to-CRLF
conversion are normal terminal behavior. Binary identity and original stream
separation are not guaranteed. Redirected host stdin/stdout are rejected; use
pipe mode for pipelines. The combined diagnostic tail is limited to 1 MiB.
Recognized failed Python commands receive one explanation on stderr after terminal
restoration. Interactive REPL exceptions followed by a successful exit do not
produce cards. ANSI forwarding is supported, but screen reconstruction, job-control
transparency, suspended children and arbitrary full-screen applications are not
guaranteed. A permanently blocked output sink can still block forwarding.

The host terminal modes and signal handlers are saved and restored on ordinary
exit, cancellation and transport errors. SIGKILL or a host crash cannot provide
that guarantee. POSIX processes that deliberately detach from the session may
outlive cleanup. ConPTY clients belong to a kill-on-close Windows Job Object:
remaining descendants are terminated when the main client ends or transport fails.
Windows uses a separate, short-lived owner process to bound ConPTY shutdown on
older Windows builds. Input/output are UTF-8/VT text, so invalid bytes, NUL, cursor
movement, wrapping and screen redraws need not survive as original log bytes.
The analyzer strips ANSI but does not reconstruct a screen; complex redraws can
produce incomplete or unrecognized diagnostics.

Automated tests use isolated real ConPTY sessions and nested console handles on
Windows, and nested POSIX PTYs on Linux and in the manual macOS workflow. User-reported manual checks
cover Windows Terminal and VS Code ConPTY plus selected WSL Bash/Zsh sessions;
the [acceptance record](https://github.com/ErrLens/errlens-cli/blob/main/docs/manual-acceptance.md) preserves untested combinations.
Legacy console hosts, detailed REPL editing, Windows 10 lifecycle behavior and
physical macOS hosts are not fully manually qualified. See
[Windows ConPTY notes](https://github.com/ErrLens/errlens-cli/blob/main/docs/windows-conpty.md) for lifecycle details.

## Development and checks

```console
python -m pytest
python -m mypy
python -m pip check
python -m build
```

The build creates a wheel and source distribution in `dist/`. GitHub Actions #6
passed all 11 jobs for `84dbb9c927b1b0eaf3ac6efc50863b9f0ef72836`, covering
Windows, Ubuntu and macOS on Python 3.11–3.13 plus Windows/Ubuntu wheel installation.
Hosted macOS runners were unavailable in [CI #8](https://github.com/ErrLens/errlens-cli/actions/runs/43235376928).
The required Tests workflow temporarily runs Linux and Windows on Python 3.11–3.13
and both packaging jobs. macOS tests remain available through a separate manual
workflow. Earlier macOS passes apply to their tested commits. The release candidate
has yet to be tested on macOS. The [release guide](https://github.com/ErrLens/errlens-cli/blob/main/docs/releasing.md)
records when to restore macOS to the required matrix. The manual publishing workflow
can retain candidate artifacts for review.

See [CONTRIBUTING.md](https://github.com/ErrLens/errlens-cli/blob/main/CONTRIBUTING.md) for contribution guidance. ErrLens is distributed under the [MIT License](https://github.com/ErrLens/errlens-cli/blob/main/LICENSE).

## Roadmap

The current CLI focuses on local Python diagnostics, localized explanations,
opt-in shell wrappers and explicit terminal sessions. Future stages may improve
terminal compatibility and add VS Code integration, additional analyzers and
optional AI providers. Those future features are not part of the current CLI.
