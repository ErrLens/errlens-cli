"""Create disposable acceptance scripts; --check runs safe pipe scenarios only."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


SCRIPTS = {
    "name.py": "print(undefined_variable)\n",
    "module.py": "import errlens_missing_acceptance_module_7f913\n",
    "syntax.py": "if True print('broken')\n",
    "unicode.py": "print('Привет, мир! 🌍'); print('\\x1b[31mRED / Красный\\x1b[0m')\n",
    "input.py": "print('ECHO:', input('Введите имя: '))\n",
    "exit.py": "import sys; print('EXIT 7'); sys.exit(7)\n",
    "tty.py": "import sys; print([s.isatty() for s in (sys.stdin,sys.stdout,sys.stderr)])\n",
    "wait.py": "import os,time; print('PID',os.getpid(),flush=True); print('READY: press Ctrl+C',flush=True); time.sleep(600)\n",
    "resize.py": "import os,time\nlast=None\nprint('Resize window, then Ctrl+C',flush=True)\nwhile True:\n size=os.get_terminal_size(1)\n if size != last: print(size,flush=True); last=size\n time.sleep(.2)\n",
    "once.py": "from pathlib import Path\np=Path(__file__).with_name('executions.txt')\nwith p.open('a',encoding='utf-8') as f: f.write('executed\\n')\nprint(undefined_variable)\n",
}


def create(directory):
    for name, code in SCRIPTS.items():
        (directory / name).write_text(code, encoding="utf-8")


def check(directory):
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    def run(name, *, language="ru", options=(), data=None):
        return subprocess.run([sys.executable, "-m", "errlens", "run", "--lang", language,
                               *options, "--", sys.executable, str(directory / name)],
                              input=data, capture_output=True, env=environment, timeout=20)
    checks = 0
    for language in ("ru", "en"):
        for name, error in (("name.py", b"NameError"), ("module.py", b"ModuleNotFoundError"), ("syntax.py", b"SyntaxError")):
            result = run(name, language=language)
            assert result.returncode == 1 and error in result.stderr and b"ErrLens" in result.stderr, result
            checks += 1
    result = run("unicode.py")
    assert result.returncode == 0 and "Привет, мир! 🌍".encode() in result.stdout
    assert b"\x1b[31m" in result.stdout and b"ErrLens" not in result.stderr
    checks += 1
    result = run("input.py", data="Андрей 🌍\n".encode())
    assert result.returncode == 0 and "ECHO: Андрей 🌍".encode() in result.stdout
    checks += 1
    assert run("exit.py").returncode == 7
    checks += 1
    result = run("once.py")
    assert result.returncode == 1 and (directory / "executions.txt").read_text() == "executed\n"
    checks += 1
    result = run("name.py", options=("--no-explain",))
    assert result.returncode == 1 and b"NameError" in result.stderr and b"ErrLens" not in result.stderr
    checks += 1
    result = run("tty.py")
    assert result.returncode == 0 and b"False, False" in result.stdout
    checks += 1
    print(f"PASS: {checks} safe pipe checks; Python {sys.version.split()[0]}, {sys.platform}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if arguments.check:
        with tempfile.TemporaryDirectory(prefix="errlens-acceptance-") as temporary:
            directory = Path(temporary)
            create(directory)
            check(directory)
    else:
        directory = Path(tempfile.mkdtemp(prefix="errlens-acceptance-"))
        create(directory)
        print(directory)
