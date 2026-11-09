"""Real nested PTYs; never touches the user's terminal or shell profiles."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_windows_requires_console_before_launch(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows console handles")
    marker = tmp_path / "ran"
    result = subprocess.run([sys.executable, "-m", "errlens", "run", "--terminal-mode", "pty", "--",
                             sys.executable, "-c", f"open({str(marker)!r},'w').close()"],
                            capture_output=True, timeout=10)
    assert result.returncode == 125 and b"ConPTY" in result.stderr
    assert not marker.exists()
    probe = subprocess.run([sys.executable, "-c", "import errlens.cli,sys; assert 'termios' not in sys.modules; assert 'pty' not in sys.modules"],
                            capture_output=True, timeout=10)
    assert probe.returncode == 0, probe.stderr


@pytest.fixture
def terminal(tmp_path: Path):
    if os.name == "nt":
        pytest.skip("POSIX PTY")
    import errno
    import fcntl
    import pty
    import select
    import signal
    import struct
    import termios
    import time

    def execute(code, *, answers=(), resize=False):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        before = termios.tcgetattr(slave)
        process = subprocess.Popen([sys.executable, "-m", "errlens", "run", "--terminal-mode", "pty", "--",
                                    sys.executable, "-c", code], cwd=tmp_path,
                                   stdin=slave, stdout=slave, stderr=subprocess.PIPE, start_new_session=True)
        output = bytearray()
        sent = False
        try:
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.05)[0]:
                    try:
                        data = os.read(master, 65536)
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                        break
                    output.extend(data)
                if b"READY" in output and not sent:
                    if resize:
                        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 33, 101, 0, 0))
                        os.kill(process.pid, signal.SIGWINCH)
                    for answer in answers:
                        os.write(master, answer)
                    sent = True
                if process.poll() is not None:
                    # slave remains open for terminal-restoration checks; drain ready data.
                    while select.select([master], [], [], 0)[0]:
                        output.extend(os.read(master, 65536))
                    break
            assert process.poll() is not None, "PTY execution timed out"
            error = process.stderr.read()
            assert termios.tcgetattr(slave) == before
            return process.returncode, bytes(output), error
        finally:
            if process.poll() is None:
                os.kill(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            process.stderr.close()
            os.close(master)
            os.close(slave)
    return execute


def test_tty_input_unicode_colors_and_status(terminal) -> None:
    status, output, error = terminal("import sys,os; print([s.isatty() for s in (sys.stdin,sys.stdout,sys.stderr)],flush=True); "
        "fd=os.open('/dev/tty',os.O_RDWR); os.close(fd); print('READY',flush=True); print(input(),flush=True); "
        "os.write(2,b'\\x1b[31mred\\x1b[0m'); sys.exit(7)", answers=("Привет 🌍\n".encode(),))
    assert status == 7 and b"True, True, True" in output
    assert "Привет 🌍".encode() in output and b"\x1b[31mred\x1b[0m" in output
    assert b"ErrLens" not in error


def test_resize_and_ctrl_c(terminal) -> None:
    code = """import os,signal,sys,time
signal.signal(signal.SIGWINCH, lambda *_: print('SIZE',os.get_terminal_size(0),flush=True))
signal.signal(signal.SIGINT, lambda *_: sys.exit(23))
print('INITIAL',os.get_terminal_size(0),flush=True)
print('READY',flush=True)
time.sleep(10)
"""
    # Resize is signalled before Ctrl+C is queued. Wait for resize acknowledgment.
    status, output, _ = terminal(code, answers=(b"\x03",), resize=True)
    assert status == 23 and b"columns=80" in output


def test_resize_notification(terminal) -> None:
    code = "import signal,os,sys,time; signal.signal(signal.SIGWINCH,lambda *_:(print('SIZE',os.get_terminal_size(0),flush=True),sys.exit(0))); print('READY',flush=True); time.sleep(10)"
    status, output, _ = terminal(code, resize=True)
    assert status == 0 and b"columns=101, lines=33" in output


@pytest.mark.parametrize("prefix", ["", "import os;os.write(2,b'\\x1b[31m');"])
def test_traceback_is_combined_once_and_explanation_is_stderr(terminal, prefix) -> None:
    status, output, error = terminal(prefix + "print(undefined_variable)")
    assert status == 1 and output.count(b"Traceback (most recent call last):") == 1
    assert b"ErrLens" not in output
    assert "Имя не определено" in error.decode("utf-8")


def test_binary_terminal_output(terminal) -> None:
    status, output, error = terminal("import os;os.write(1,b'\\x00\\xff\\n')")
    assert status == 0 and b"\x00\xff\r\n" in output and not error


def test_child_closes_terminal_without_exiting(terminal) -> None:
    status, _, error = terminal("import os,time;os.close(0);os.close(1);os.close(2);time.sleep(30)")
    assert status == 125 and b"pty_eof" in error


def test_no_terminal_no_execution(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX")
    marker = tmp_path / "ran"
    result = subprocess.run([sys.executable, "-m", "errlens", "run", "--terminal-mode", "pty", "--",
                             sys.executable, "-c", f"open({str(marker)!r},'w').close()"],
                            capture_output=True, timeout=10)
    assert result.returncode == 125 and not marker.exists()


def test_descriptor_cleanup_and_bounded_capture() -> None:
    if os.name == "nt":
        pytest.skip("POSIX")
    import pty
    from errlens.capture import TerminalCapture
    from errlens.models import ExecutionContext
    from errlens.pty_runner import run
    master, slave = pty.openpty()
    output = os.fdopen(os.dup(slave), "wb", buffering=0)
    directory = "/proc/self/fd" if Path("/proc/self/fd").exists() else "/dev/fd"
    count = len(os.listdir(directory))
    try:
        for _ in range(3):
            capture = TerminalCapture(16)
            result = run(ExecutionContext([sys.executable, "-c", "print('x'*100)"], os.getcwd()), capture, output, input_fd=slave)
            assert result.exit_code == 0 and not result.output_complete
            assert len(capture.combined.data) == 16
            assert len(os.listdir(directory)) == count
    finally:
        output.close()
        os.close(master)
        os.close(slave)


def test_transport_error_does_not_retry_and_restores_tty(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX")
    import pty
    import termios
    from errlens.capture import TerminalCapture
    from errlens.models import ExecutionContext
    from errlens.pty_runner import run
    from errlens.runner import RunnerError
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    marker = tmp_path / "executions"
    class FailedOutput:
        def fileno(self):
            return slave
        def write(self, data):
            raise OSError("test output failure")
        def flush(self):
            pass
    try:
        command = [sys.executable, "-c", f"import os,time; open({str(marker)!r},'a').write('x'); os.write(1,b'ready'); time.sleep(30)"]
        with pytest.raises(RunnerError, match="test output failure"):
            run(ExecutionContext(command, str(tmp_path)), TerminalCapture(), FailedOutput(), input_fd=slave)
        assert marker.read_text() == "x"
        assert termios.tcgetattr(slave) == before
    finally:
        os.close(master)
        os.close(slave)
