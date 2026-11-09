"""PTY dispatch and POSIX transport; platform-specific imports remain lazy."""

import os
import signal
import subprocess
import sys
import threading
import time
from typing import BinaryIO

from errlens.capture import TerminalCapture
from errlens.models import ExecutionContext, ExecutionResult
from errlens.runner import RunnerError


def run(context: ExecutionContext, capture: TerminalCapture, stdout: BinaryIO,
        *, input_fd: int = 0) -> ExecutionResult:
    if sys.platform == "win32":
        from errlens.conpty_runner import run as run_conpty
        return run_conpty(context, capture, stdout, input_fd=input_fd)
    import errno
    import fcntl
    import pty
    import select
    import termios
    import tty

    if threading.current_thread() is not threading.main_thread():
        raise RunnerError("pty", "PTY mode must run on the main thread")
    if not os.isatty(input_fd) or not os.isatty(stdout.fileno()):
        raise RunnerError("pty", "PTY mode requires terminal stdin and stdout; use pipe for redirection")
    saved = termios.tcgetattr(input_fd)
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGWINCH)}
    master = slave = error_read = error_write = -1
    process: subprocess.Popen[bytes] | None = None
    cancel = False
    resized = True
    completed = False

    def on_interrupt(signum: int, frame: object) -> None:
        nonlocal cancel
        cancel = True

    def on_resize(signum: int, frame: object) -> None:
        nonlocal resized
        resized = True

    def send(number: int, *, initial: bool = False) -> None:
        if process is None:
            return
        groups = {process.pid} if initial else set()
        try:
            groups.add(os.tcgetpgrp(master))
        except OSError:
            groups.add(process.pid)
        for group in groups:
            if group > 0 and group != os.getpgrp():
                try:
                    os.killpg(group, number)
                except ProcessLookupError:
                    pass

    try:
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, fcntl.ioctl(input_fd, termios.TIOCGWINSZ, b"\0" * 8))
        error_read, error_write = os.pipe()
        process = subprocess.Popen(
            [sys.executable, "-m", "errlens._pty_child", str(error_write), *context.command],
            cwd=context.cwd, stdin=slave, stdout=slave, stderr=slave,
            pass_fds=(error_write,), start_new_session=True, shell=False,
        )
        os.close(slave)
        slave = -1
        os.close(error_write)
        error_write = -1
        os.set_blocking(master, False)
        signal.signal(signal.SIGINT, on_interrupt)
        signal.signal(signal.SIGWINCH, on_resize)
        tty.setraw(input_fd, termios.TCSANOW)
        pending = bytearray()
        eof = False
        checking_launch = True
        cancel_deadline: float | None = None
        drain_deadline: float | None = None
        eof_deadline: float | None = None
        while True:
            now = time.monotonic()
            if resized:
                fcntl.ioctl(master, termios.TIOCSWINSZ,
                            fcntl.ioctl(input_fd, termios.TIOCGWINSZ, b"\0" * 8))
                resized = False
            if cancel and cancel_deadline is None:
                send(signal.SIGINT)
                cancel_deadline = now + 1
            if cancel_deadline is not None and now >= cancel_deadline:
                send(signal.SIGKILL, initial=True)
            status = process.poll()
            if eof_deadline is not None and status is None and now >= eof_deadline:
                raise RunnerError("pty_eof", "Terminal closed while child remained alive")
            if status is not None:
                if eof:
                    break
                if drain_deadline is None:
                    drain_deadline = now + 1
                if now >= drain_deadline:
                    raise RunnerError("drain", "PTY did not close after process exit")
            reads = ([] if eof else [master]) + ([input_fd] if len(pending) < 65536 and status is None else [])
            if checking_launch:
                reads.append(error_read)
            ready, writable, _ = select.select(reads, [master] if pending and not eof else [], [], 0.05)
            if error_read in ready:
                message = os.read(error_read, 4096)
                checking_launch = False
                if message:
                    raise RunnerError("pty_launch", message.decode("utf-8", errors="replace"),
                                      127 if message.startswith(b"2:") else 126)
            if master in ready:
                try:
                    data = os.read(master, 65536)
                except BlockingIOError:
                    data = None
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    data = b""  # Linux slave hangup; macOS commonly returns EOF.
                if data == b"":
                    eof = True
                    eof_deadline = now + 1
                elif data:
                    capture.combined.append(data)
                    offset = 0
                    while offset < len(data):
                        written = stdout.write(data[offset:])
                        if written is None or written <= 0:
                            raise OSError("Output stream made no progress")
                        offset += written
                    stdout.flush()
            if input_fd in ready:
                data = os.read(input_fd, 4096)
                if not data:
                    raise RunnerError("pty_input", "Host terminal input closed")
                pending.extend(data)
            if master in writable and not eof:
                try:
                    written = os.write(master, pending)
                    del pending[:written]
                except BlockingIOError:
                    pass
        completed = True
        return ExecutionResult(status, cancel or status == -signal.SIGINT, not capture.truncated)
    except BrokenPipeError as exc:
        raise RunnerError("broken_pipe", str(exc), 141) from exc
    except OSError as exc:
        raise RunnerError("pty", str(exc)) from exc
    finally:
        try:
            if process is not None:
                if process.poll() is None or not completed:
                    send(signal.SIGKILL, initial=True)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired as exc:
                    raise RunnerError("cleanup", "PTY child did not exit after kill") from exc
        finally:
            try:
                termios.tcsetattr(input_fd, termios.TCSANOW, saved)
            finally:
                for number, handler in previous.items():
                    signal.signal(number, handler)
                for fd in (master, slave, error_read, error_write):
                    if fd >= 0:
                        os.close(fd)
