# ErrLens 0.1.0

Draft GitHub release notes — not published. Verify the final candidate and
configure Trusted Publishing before using these notes for a public release.

ErrLens adds local Russian or English explanations to recognized Python errors.
Run a command with `errlens run python main.py`; choose English with `--lang en`
or suppress explanations with `--no-explain` before the command.

- Streaming pipe execution by default, bounded capture and child exit codes.
- Explicit PTY on Linux/macOS and ConPTY on Windows for terminal-dependent programs.
- Optional PowerShell 7, Bash and Zsh wrappers for `python`.
- Offline rules for import, syntax, name, type, attribute, key and file errors.
- MIT license; requires Python 3.11+. CI qualifies CPython 3.11–3.13.

After PyPI publication: `python -m pip install errlens-cli==0.1.0`.
Before publication use a verified `errlens_cli-0.1.0-py3-none-any.whl` or a local
checkout (`python -m pip install .`). The command and Python import remain
`errlens`; the distribution is `errlens-cli`, not the existing PyPI `errlens`.

Terminal mode combines child streams and may transform bytes, colors and line
endings. Full-screen apps, complex redraws and transparent pipelines are not
guaranteed. See the README and manual-acceptance record for scope and limitations.
No automatic code fixes, network analysis or arbitrary-command interception.
