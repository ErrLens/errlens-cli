"""Real CLI subprocesses use deadlines so a regression cannot hang CI forever."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

import pytest


def execute(code: str, *args: str, **kwargs):
    return subprocess.run([sys.executable, "-m", "errlens", "run", sys.executable,
                           "-c", code, *args], capture_output=True, timeout=15, **kwargs)


@pytest.mark.parametrize("status", [0, 1, 7, 99])
def test_exit_codes_and_streams(status: int) -> None:
    result = execute(f"import os,sys; os.write(1,b'out'); os.write(2,b'err'); sys.exit({status})")
    assert result.returncode == status
    assert result.stdout == b"out" and result.stderr == b"err"


def test_binary_ansi_unicode_and_arguments() -> None:
    result = execute("import os,sys; os.write(1,bytes(range(256))); "
                     "os.write(2,sys.argv[1].encode('utf-8'))", "Привет с пробелами 🌍")
    assert result.stdout == bytes(range(256))
    assert result.stderr == "Привет с пробелами 🌍".encode()


def test_large_simultaneous_output() -> None:
    code = ("import os,threading; "
            "t=threading.Thread(target=lambda:[os.write(2,b'e'*8192) for _ in range(256)]); "
            "t.start(); [os.write(1,b'o'*8192) for _ in range(256)]; t.join()")
    result = execute(code)
    assert result.returncode == 0
    assert result.stdout == b"o" * (2 * 1024 * 1024)
    assert result.stderr == b"e" * (2 * 1024 * 1024)


def test_file_with_spaces_and_redirect(tmp_path: Path) -> None:
    script = tmp_path / "скрипт с пробелами.py"
    script.write_text("import os; os.write(1,b'exact\\x00\\r\\n'); os.write(2,b'err')", encoding="utf-8")
    destination = tmp_path / "out.bin"
    with destination.open("wb") as output:
        result = subprocess.run([sys.executable, "-m", "errlens", "run", sys.executable,
                                 str(script)], stdout=output, stderr=subprocess.PIPE, timeout=15)
    assert result.returncode == 0 and result.stderr == b"err"
    assert destination.read_bytes() == b"exact\x00\r\n"


def test_missing_executable() -> None:
    result = subprocess.run([sys.executable, "-m", "errlens", "run", "errlens-missing-8f14e"],
                            capture_output=True, timeout=15)
    assert result.returncode == 127 and result.stdout == b""
    assert b"ErrLens" in result.stderr


def test_child_help_and_version() -> None:
    for option in ("--help", "--version"):
        result = subprocess.run([sys.executable, "-m", "errlens", "run", sys.executable, option],
                                capture_output=True, timeout=15)
        direct = subprocess.run([sys.executable, option], capture_output=True, timeout=15)
        assert result.returncode == direct.returncode == 0
        assert (result.stdout, result.stderr) == (direct.stdout, direct.stderr)


def test_streaming_before_child_exit() -> None:
    command = [sys.executable, "-m", "errlens", "run", sys.executable, "-c",
               "import os,time; os.write(1,b'first'); time.sleep(2); os.write(1,b'last')"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    first: list[bytes] = []
    reader = threading.Thread(target=lambda: first.append(process.stdout.read(5)), daemon=True)
    reader.start()
    try:
        reader.join(timeout=1.5)
        assert first == [b"first"] and process.poll() is None
        out, err = process.communicate(timeout=10)
        assert out == b"last" and err == b"" and process.returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        reader.join(timeout=1)


def test_broken_output_pipe() -> None:
    process = subprocess.Popen([sys.executable, "-m", "errlens", "run", sys.executable,
                                "-c", "import os,time; time.sleep(.3); os.write(1,b'x'*10000); time.sleep(10)"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.stdout.close()
    try:
        assert process.wait(timeout=10) == 141
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stderr.close()


def test_ctrl_c_python_handler_in_isolated_process() -> None:
    # Exercise Python's SIGINT/KeyboardInterrupt entry point without sending a
    # console event to pytest's process. Windows console control is tested below.
    script = (
        "import _thread,threading,sys,io,os; "
        "from errlens.runner import run; from errlens.models import ExecutionContext; "
        "from errlens.capture import Capture; "
        "timer=threading.Timer(.5,_thread.interrupt_main); timer.start(); "
        "result=run(ExecutionContext([sys.executable,'-c','import time; time.sleep(30)'],os.getcwd()),"
        "Capture(),io.BytesIO(),io.BytesIO()); timer.join(); "
        "sys.exit(130 if result.interrupted else 1)"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=10)
    assert result.returncode == 130, result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal status")
def test_signal_exit_mapping() -> None:
    result = execute("import os,signal; os.kill(os.getpid(),signal.SIGTERM)")
    assert result.returncode == 128 + signal.SIGTERM


def test_ctrl_c_isolated_group() -> None:
    if os.name == "nt":
        import ctypes
        if not ctypes.windll.kernel32.GetConsoleCP():
            pytest.skip("No shared Windows console for CTRL_BREAK_EVENT")
    process = subprocess.Popen(
        [sys.executable, "-m", "errlens", "run", sys.executable, "-c",
         "import os,time; os.write(1,b'ready'); time.sleep(30)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    ready: list[bytes] = []
    reader = threading.Thread(target=lambda: ready.append(process.stdout.read(5)), daemon=True)
    reader.start()
    try:
        reader.join(timeout=5)
        assert ready == [b"ready"]
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        assert process.wait(timeout=8) == 130
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
