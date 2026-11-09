# Actions #4 diagnosis

Run: https://github.com/ErrLens/errlens-cli/actions/runs/42619247555
Commit: cdf8e26d1acf2c392115dd6a96b132116c661b34.
Full logs were retrieved using `gh run view --log`. The local copy is ignored.

## macOS Python 3.11, 3.12, 3.13

Each job has the same eight failures in `tests/integration/test_pty.py`:

1. `test_tty_input_unicode_colors_and_status`
2. `test_resize_and_ctrl_c`
3. `test_resize_notification`
4. `test_traceback_is_combined_once_and_explanation_is_stderr[]`
5. `test_traceback_is_combined_once_and_explanation_is_stderr[ANSI prefix]`
6. `test_binary_terminal_output`
7. `test_child_closes_terminal_without_exiting`
8. `test_transport_error_does_not_retry_and_restores_tty`

All fail at the terminal-state comparison, seven in the common harness and one
in the transport-error test. The local-flag difference is exactly
`536872395 ^ 1483 == 0x20000000`, Darwin PENDIN. The snapshots otherwise match.
[XNU tty.c](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/tty.c)
sets PENDIN on transition to canonical input and preserves it while applying
the requested flags. This is kernel pending-input state, not failure to restore
the saved terminal modes. Linux does not expose this same Darwin transition.

Only Darwin PENDIN is excluded from test comparisons. Every other flag, speed
and control character remains compared. A regression verifies this exact change
and verifies that an ECHO change still fails; the saved snapshot is not mutated.
The backend remains unchanged. No skip/xfail was added. Another macOS CI run
must execute the functional assertions previously masked by this comparison;
these logs alone do not prove all controlling-terminal, resize, signal and EOF
assertions pass on Darwin.

## Windows Python 3.13

Two failures: `test_real_cli_and_explanation_policy[traceback-ru]` and
`test_real_cli_and_explanation_policy[traceback-en]`. The failed run uses 3.13.17.
The downloadable logs themselves contain abbreviated pytest string diffs (`...`)
rather than the complete ConPTY transcript. A Rich frame and traceback are visible,
but neither a complete diagnostic card nor the raw byte stream can be recovered
from these abbreviated representations. Unicode escapes in a Python repr and
CRLF/VT sequences are not by themselves evidence of an encoding defect.

Local evidence: 20 nested English CLI runs on 3.13.15 matched; 15 direct real
ConPTY captures at widths 40/80/120 produced complete structured diagnostics;
the six explanation-related tests also passed on an isolated official portable
CPython 3.13.17 runtime. No local missing bytes or failing language assertion was
observed. This does not exclude an OS-specific ConPTY issue on the CI host.

No Windows product fix or relaxed assertion is justified by that evidence yet.
On failure, the test now emits its entire raw base64/UTF-8 transcript, status,
Python version and configured size into captured stdout, which avoids pytest's
abbreviated assertion diff. The expected language title and status checks remain
unchanged. A new Windows CI run is needed to determine whether the emitted card
is incomplete/neutral, or VT redraw/wrapping obscures text, or bytes are missing.
Do not label this Windows failure fixed until that evidence is available.

Version stays 0.1.0, pipe remains the default. No commit or push is performed.

## Local checks after the changes

- Windows 3.13.15 full pytest: 292 passed, 20 skipped.
- WSL Python 3.12.3 full pytest: 279 passed, 33 skipped.
- Strict mypy on Windows and WSL: 21 source files passed.
- Official portable Windows Python 3.13.17, explanation-related subset:
  6 passed (before diagnostic-only assertion logging was added).
- `git diff --check`: passed. No new skip/xfail, runtime dependency or backend change.
