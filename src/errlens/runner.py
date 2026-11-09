"""Binary forwarding with independent readers and bounded process cleanup."""

import os
import errno
import queue
import select
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import BinaryIO, Literal
from types import FrameType

from errlens.capture import Capture
from errlens.models import ExecutionContext, ExecutionResult

CHUNK_SIZE = 64 * 1024


class RunnerError(Exception):
    """ErrLens infrastructure failure, distinct from a child's nonzero status."""

    def __init__(self, kind: str, detail: str, exit_code: int = 125) -> None:
        super().__init__(detail)
        self.kind = kind
        self.exit_code = exit_code


def _broken_pipe(error: OSError | ValueError, destination: BinaryIO) -> bool:
    if isinstance(error, BrokenPipeError):
        return True
    # Windows CRT can surface a closed redirected pipe as EINVAL, not EPIPE.
    # Restrict the mapping to actual pipe handles; EINVAL on files stays an error.
    if sys.platform == "win32" and isinstance(error, OSError) and error.errno == errno.EINVAL:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        try:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            get_type = kernel.GetFileType
            get_type.argtypes = [wintypes.HANDLE]
            get_type.restype = wintypes.DWORD
            return bool(get_type(msvcrt.get_osfhandle(destination.fileno())) == 3)
        except (OSError, ValueError):
            return False
    return False


def _available(stream: BinaryIO) -> int:
    """Poll pipes without an uncancellable blocking read (also on Python 3.11)."""
    if sys.platform != "win32":
        return CHUNK_SIZE if select.select([stream], [], [], 0.02)[0] else 0
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    peek = kernel.PeekNamedPipe
    peek.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                     wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    peek.restype = wintypes.BOOL
    available = wintypes.DWORD()
    if not peek(msvcrt.get_osfhandle(stream.fileno()), None, 0, None,
                ctypes.byref(available), None):
        error = ctypes.get_last_error()
        if error in (109, 233):  # broken pipe / no process on other end
            return -1
        raise ctypes.WinError(error)
    return min(available.value, CHUNK_SIZE)


def _pump(
    source: BinaryIO, destination: BinaryIO, name: Literal["stdout", "stderr"],
    capture: Capture, stop: threading.Event, errors: queue.SimpleQueue[RunnerError],
) -> None:
    try:
        while not stop.is_set():
            try:
                available = _available(source)
                if available < 0:
                    return
                if available == 0:
                    stop.wait(0.01)
                    continue
                chunk = os.read(source.fileno(), available)
            except (OSError, ValueError) as exc:
                errors.put(RunnerError("read", f"{name}: {exc}"))
                return
            if not chunk:
                return
            capture.append(name, chunk)
            try:
                offset = 0
                while offset < len(chunk):
                    written = destination.write(chunk[offset:])
                    if written is None or written <= 0:
                        raise OSError("Output stream made no progress")
                    offset += written
                destination.flush()
            except (OSError, ValueError) as exc:
                broken = _broken_pipe(exc, destination)
                errors.put(RunnerError("broken_pipe" if broken else "write", f"{name}: {exc}",
                                       141 if broken else 125))
                return
    except Exception as exc:
        errors.put(RunnerError("reader", f"{name}: {type(exc).__name__}: {exc}"))
    finally:
        try:
            source.close()
        except OSError as exc:
            errors.put(RunnerError("read", f"{name}: {exc}"))


@contextmanager
def _interrupts(cancel: threading.Event) -> Iterator[None]:
    """Handlers record cancellation; no asynchronous exceptions during cleanup."""
    previous: dict[signal.Signals, Callable[[int, FrameType | None], object] | int | None] = {}
    if threading.current_thread() is threading.main_thread():
        signals = [signal.SIGINT]
        if sys.platform == "win32":
            signals.append(signal.SIGBREAK)
        for number in signals:
            previous[number] = signal.getsignal(number)
            if previous[number] != signal.SIG_IGN:
                signal.signal(number, lambda signum, frame: cancel.set())
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _signal_group(process: subprocess.Popen[bytes], *, force: bool = False) -> None:
    try:
        if sys.platform != "win32":
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGINT)
        elif process.poll() is None:
            if force:
                process.kill()
            else:
                process.send_signal(signal.CTRL_BREAK_EVENT)
    except ProcessLookupError:
        pass
    except OSError:
        if process.poll() is None:
            process.kill()


def run(
    context: ExecutionContext, capture: Capture, stdout: BinaryIO, stderr: BinaryIO,
    *, cancel: threading.Event | None = None, interrupt_timeout: float = 1.0,
    drain_timeout: float = 1.0,
) -> ExecutionResult:
    """Run an argv sequence, inheriting stdin and environment (metadata is inert).

    Single-use capture is supplied by the caller. Main-thread use handles Ctrl+C;
    callers in other threads must supply a cancellation Event. Exit signals remain
    negative in the result. No analyzers, rendering or translations are invoked.
    """
    if interrupt_timeout <= 0 or drain_timeout <= 0:
        raise ValueError("Timeouts must be positive")
    cancellation = cancel if cancel is not None else threading.Event()
    errors: queue.SimpleQueue[RunnerError] = queue.SimpleQueue()
    stop = threading.Event()
    readers: list[threading.Thread] = []
    process: subprocess.Popen[bytes] | None = None
    with _interrupts(cancellation):
        try:
            try:
                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
                process = subprocess.Popen(
                    context.command, cwd=context.cwd, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, bufsize=0, shell=False,
                    start_new_session=os.name == "posix",
                    creationflags=creation_flags,
                )
            except FileNotFoundError as exc:
                raise RunnerError("not_found", str(exc), 127) from exc
            except PermissionError as exc:
                raise RunnerError("permission", str(exc), 126) from exc
            except (OSError, ValueError) as exc:
                raise RunnerError("launch", str(exc)) from exc
            assert process.stdout is not None and process.stderr is not None
            for name, source, target in (
                ("stdout", process.stdout, stdout), ("stderr", process.stderr, stderr),
            ):
                reader = threading.Thread(
                    target=_pump, args=(source, target, name, capture, stop, errors),
                    name=f"errlens-{name}", daemon=True,
                )
                reader.start()
                readers.append(reader)
            interrupted = False
            interrupt_deadline: float | None = None
            drain_deadline: float | None = None
            while True:
                if not errors.empty():
                    raise errors.get()
                now = time.monotonic()
                if cancellation.is_set() and not interrupted:
                    interrupted = True
                    _signal_group(process)
                    interrupt_deadline = now + interrupt_timeout
                if interrupt_deadline is not None and now >= interrupt_deadline:
                    _signal_group(process, force=True)
                    interrupt_deadline = None
                status = process.poll()
                if status is not None:
                    if not any(reader.is_alive() for reader in readers):
                        break
                    if drain_deadline is None:
                        drain_deadline = now + drain_timeout
                    if now >= drain_deadline:
                        raise RunnerError("drain", "Output pipes did not close after process exit")
                time.sleep(0.01)
            if not errors.empty():
                raise errors.get()
            return ExecutionResult(status, interrupted, not capture.truncated)
        finally:
            stop.set()
            if process is not None:
                if process.poll() is None or cancellation.is_set() or any(r.is_alive() for r in readers):
                    _signal_group(process, force=True)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired as exc:
                    raise RunnerError("cleanup", "Process did not exit after kill") from exc
                for reader in readers:
                    reader.join(timeout=0.5)
                # Readers own their source handles; never close/reuse an fd while
                # a reader is active. Normally polling makes both joins immediate.
                if not any(reader.is_alive() for reader in readers):
                    for pipe in (process.stdout, process.stderr):
                        if pipe is not None and not pipe.closed:
                            pipe.close()
