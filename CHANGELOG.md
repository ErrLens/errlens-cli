# Changelog

## 0.1.0 — release candidate (unreleased)

Initial CLI candidate. The package metadata remains `0.1.0`; no tag, release date
or PyPI publication is implied by this entry.
Distribution: `errlens-cli`; Python import: `errlens`; command: `errlens`.

### Added

- `errlens run` with streaming stdout/stderr, bounded diagnostic capture and
  child exit-status propagation. Pipe is the default.
- Rule-based offline explanations in Russian and English for recognized CPython
  tracebacks, with conservative handling of incomplete diagnostics and chains.
- Rich terminal cards and plain redirected explanations; `--lang` and `--no-explain`.
- Explicit `--terminal-mode pty`: POSIX PTY on Linux/macOS and native ConPTY on Windows.
- Opt-in PowerShell 7, Bash and Zsh integration for `python`, with explicit
  install/status/uninstall, temporary bypass and profile backup/preservation.
- MIT licensing, packaged translations, CI across Python 3.11–3.13 on three OSes,
  wheel/sdist checks and recorded terminal acceptance evidence.

### Fixed during candidate stabilization

- Windows localized Unicode output with non-UTF-8 host text wrappers.
- Darwin termios assertions account only for kernel-managed PENDIN state.
- Diagnostic-only VT normalization preserves horizontal traceback indentation,
  with bounded cursor/text expansion and conservative incomplete flags.

### Limitations

- Terminal mode merges child output and does not preserve binary identity.
- Full-screen emulation, complex redraw/grapheme reconstruction, transparent
  pipelines and automatic exception cards inside a successful REPL are not provided.
- Shell integration is explicit and wraps only `python`; it does not intercept
  arbitrary commands. No fixes or recommended commands are executed automatically.
- Some physical host combinations remain NOT TESTED. The historical Zsh prompt
  observation has no established root cause; a clean Zsh session was successful.
- The original PyPI name `errlens` conflicts with an existing distribution.
  The maintainer selected `errlens-cli` instead; publication still requires
  Trusted Publisher setup and approval. See `docs/releasing.md`.
