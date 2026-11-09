# Python diagnostic corpus

`python_diagnostics.json` contains synthetic cases with expected structured facts:
all supported error types, paths, chains, multiline messages, groups, ANSI and
incomplete text. These are format boundary examples, not executable programs.

`recorded_python313.json` contains actual CPython 3.13.15 stderr captured on
Windows. Runtime/platform and the generating Python code are stored with the
samples. The integration suite additionally runs real programs on the interpreter
used by CI, preserving the original bytes before invoking the analyzer.

No actual project source files or secrets are needed to analyze these samples.
