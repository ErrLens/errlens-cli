# Python diagnostic corpus

`python_diagnostics.json` contains synthetic cases with expected structured facts:
all supported error types, paths, chains, multiline messages, groups, ANSI and
incomplete text. These are format boundary examples, not executable programs.

`recorded_python313.json` contains actual CPython 3.13.15 stderr captured on
Windows. Runtime/platform and the generating Python code are stored with the
samples. The integration suite additionally runs real programs on the interpreter
used by CI, preserving the original bytes before invoking the analyzer.

No actual project source files or secrets are needed to analyze these samples.

`conpty_python313.json` contains reduced raw traceback portions from the RU/EN
Windows Python 3.13.17 transcripts in Actions run 42622235347. Host paths,
window titles and explanation cards were removed; original traceback VT, CRLF,
blank redraw rows and color sequences are retained. These cases exercise
cursor-forward indentation and must produce complete NameError explanations.

Diagnostic VT normalization is line-local, not a screen emulator: CUF/CUB/CHA,
ECH/EL, CR/LF, tabs and backspace are handled; vertical redraw, automatic wrapping
and complex grapheme layout are not reconstructed. Cursor columns are capped at
4096, total normalized text at 1,048,576 characters, and combining marks per cell
are bounded. Hitting a limit marks diagnostics incomplete rather than silently
claiming a complete traceback. These limits never apply to forwarded output.
