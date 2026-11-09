"""Windows terminal frontend, with a bounded, disposable ConPTY owner.

run_session is the private headless harness used by integration tests. The CLI
requires real console handles; redirected users keep the default pipe transport.
"""

from collections.abc import Callable
import json
import os
import queue
import signal
import struct
import subprocess
import sys
import threading
import time
from typing import BinaryIO

from errlens._conpty_worker import receive, send
from errlens.capture import TerminalCapture
from errlens.models import ExecutionContext, ExecutionResult
from errlens.runner import RunnerError


def run_session(context: ExecutionContext, capture: TerminalCapture, stdout: BinaryIO,
                *, read_input: Callable[[], bytes | None] = lambda: None,
                get_size: Callable[[], tuple[int, int]] = lambda: (80, 24)) -> ExecutionResult:
    """Run once; callbacks are nonblocking, sizes are (columns, rows)."""
    if sys.platform != "win32":
        raise RunnerError("unsupported", "ConPTY requires Windows")
    if threading.current_thread() is not threading.main_thread():
        raise RunnerError("conpty", "ConPTY mode must run on the main thread")
    process: subprocess.Popen[bytes] | None = None
    incoming: queue.Queue[tuple[bytes, bytes] | Exception] = queue.Queue(16)
    outgoing: queue.Queue[tuple[bytes, bytes]] = queue.Queue(16)
    stop = threading.Event()
    interrupted = False
    previous = signal.getsignal(signal.SIGINT)
    threads: list[threading.Thread] = []

    def on_interrupt(signum: int, frame: object) -> None:
        nonlocal interrupted
        interrupted = True

    def publish(item: tuple[bytes, bytes] | Exception) -> None:
        while not stop.is_set():
            try:
                incoming.put(item, timeout=0.05)
                return
            except queue.Full:
                pass

    def reader(stream: BinaryIO) -> None:
        try:
            while not stop.is_set():
                publish(receive(stream))
        except Exception as exc:
            publish(exc)

    def writer(stream: BinaryIO) -> None:
        try:
            while not stop.is_set():
                try:
                    kind, data = outgoing.get(timeout=0.05)
                except queue.Empty:
                    continue
                send(stream, kind, data)
        except Exception as exc:
            publish(exc)

    try:
        size = get_size()
        configuration = json.dumps({"command": context.command, "cwd": context.cwd,
                                    "size": size}, ensure_ascii=False).encode("utf-8")
        if len(configuration) > 65536 or not all(1 <= n <= 32767 for n in size):
            raise RunnerError("conpty", "ConPTY configuration exceeds transport limits")
        # An independent hidden console protects the owner from host Ctrl+C
        # without inheriting CREATE_NEW_PROCESS_GROUP's ignored Ctrl+C flag.
        # Windows venv python.exe is a redirector which starts another process.
        # Own the real CPython process so kill()/wait() bound the actual owner.
        # Reuse the current import path to retain editable/wheel/venv resolution.
        bootstrap = ("import runpy,sys;sys.path[:]=" + repr(sys.path) +
                     ";runpy.run_module('errlens._conpty_worker',run_name='__main__')")
        executable = getattr(sys, "_base_executable", sys.executable)
        process = subprocess.Popen([executable, "-c", bootstrap],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, bufsize=0, shell=False,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        assert process.stdin is not None and process.stdout is not None
        threads = [threading.Thread(target=reader, args=(process.stdout,), daemon=True),
                   threading.Thread(target=writer, args=(process.stdin,), daemon=True)]
        for thread in threads:
            thread.start()
        outgoing.put_nowait((b"C", configuration))
        signal.signal(signal.SIGINT, on_interrupt)
        ready = False
        status: int | None = None
        deadline: float | None = time.monotonic() + 15  # bounded startup, not execution
        cancel_at: float | None = None
        while True:
            now = time.monotonic()
            if deadline is not None and now > deadline:
                raise RunnerError("conpty", "ConPTY startup/cleanup timed out")
            if interrupted and cancel_at is None:
                cancel_at = now + 1
                if ready and status is None:
                    try:
                        outgoing.put_nowait((b"I", b"\x03"))
                    except queue.Full:
                        pass  # blocked input still has bounded owner/tree termination
            if cancel_at is not None and now > cancel_at:
                return ExecutionResult(status, True, not capture.truncated)
            if ready and status is None and not outgoing.full():
                new_size = get_size()
                if new_size != size:
                    if not all(1 <= n <= 32767 for n in new_size):
                        raise RunnerError("conpty", "Invalid host terminal size")
                    outgoing.put_nowait((b"W", struct.pack("!HH", *new_size)))
                    size = new_size
                if not outgoing.full():
                    data = read_input()
                    if data:
                        if len(data) > 4096:
                            raise RunnerError("conpty", "Host input chunk exceeds 4096 bytes")
                        outgoing.put_nowait((b"I", data))
            try:
                item = incoming.get(timeout=0.02)
            except queue.Empty:
                if process.poll() is not None and not any(t.is_alive() for t in threads[:1]):
                    raise RunnerError("conpty", "ConPTY owner exited without a completion record")
                continue
            if isinstance(item, Exception):
                raise RunnerError("conpty", str(item)) from item
            kind, payload = item
            if kind == b"O":
                capture.combined.append(payload)
                offset = 0
                while offset < len(payload):
                    count = stdout.write(payload[offset:])
                    if count is None or count <= 0:
                        raise OSError("Output stream made no progress")
                    offset += count
                stdout.flush()
            elif kind == b"R":
                ready, deadline = True, None
            elif kind == b"S":
                status = struct.unpack("!I", payload)[0]
                deadline = time.monotonic() + 4
            elif kind == b"E":
                error = json.loads(payload)
                raise RunnerError("conpty", error["detail"], error["code"])
            elif kind == b"D" and status is not None:
                return ExecutionResult(status, interrupted or status == 0xc000013a, not capture.truncated)
            else:
                raise RunnerError("conpty", "Invalid ConPTY owner response")
    except BrokenPipeError as exc:
        raise RunnerError("broken_pipe", str(exc), 141) from exc
    except OSError as exc:
        raise RunnerError("conpty", str(exc)) from exc
    finally:
        stop.set()
        signal.signal(signal.SIGINT, previous)
        if process is not None:
            # Closing the owner's job kills all clients, including descendants.
            if process.poll() is None:
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired as exc:
                raise RunnerError("cleanup", "ConPTY owner did not exit after termination") from exc
            from errlens._conpty import cancel_thread
            for thread in threads:
                if thread.is_alive() and thread.native_id is not None:
                    cancel_thread(thread.native_id)
                thread.join(0.5)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()


def run(context: ExecutionContext, capture: TerminalCapture, stdout: BinaryIO,
        *, input_fd: int = 0) -> ExecutionResult:
    """Attach only to actual Windows console handles, restoring both modes."""
    if sys.platform != "win32":
        raise RunnerError("unsupported", "ConPTY requires Windows")
    import ctypes as c
    from ctypes import wintypes as w
    import msvcrt
    from errlens._conpty import api, cancel_thread, check, get_mode, screen_info, SCREEN, set_mode
    try:
        input_handle = msvcrt.get_osfhandle(input_fd)
        output_handle = msvcrt.get_osfhandle(stdout.fileno())
        input_mode, output_mode = w.DWORD(), w.DWORD()
        if not get_mode(input_handle, c.byref(input_mode)) or not get_mode(output_handle, c.byref(output_mode)):
            raise RunnerError("conpty", "ConPTY requires console stdin and stdout; use pipe for redirection")
    except (OSError, ValueError) as exc:
        raise RunnerError("conpty", str(exc)) from exc
    if threading.current_thread() is not threading.main_thread():
        raise RunnerError("conpty", "ConPTY mode must run on the main thread")
    inputs: queue.Queue[bytes | Exception] = queue.Queue(16)
    stop = threading.Event()
    read_console = api("ReadConsoleW", w.BOOL, [w.HANDLE, w.LPVOID, w.DWORD, c.POINTER(w.DWORD), w.LPVOID])

    def read_host() -> None:
        try:
            pending = b""
            while not stop.is_set():
                buffer, count = c.create_unicode_buffer(512), w.DWORD()
                check(read_console(input_handle, buffer, 512, c.byref(count), None))
                # A read can split a UTF-16 surrogate pair.
                pending += c.string_at(c.addressof(buffer), count.value * 2)
                if pending and 0xd800 <= int.from_bytes(pending[-2:], "little") <= 0xdbff:
                    text, pending = pending[:-2], pending[-2:]
                else:
                    text, pending = pending, b""
                data = text.decode("utf-16-le", errors="replace").encode("utf-8")
                while not stop.is_set():
                    try:
                        inputs.put(data, timeout=0.05)
                        break
                    except queue.Full:
                        pass
        except Exception as exc:
            if not stop.is_set():
                try:
                    inputs.put_nowait(exc)
                except queue.Full:
                    pass

    def read_input() -> bytes | None:
        try:
            value = inputs.get_nowait()
        except queue.Empty:
            return None
        if isinstance(value, Exception):
            raise RunnerError("conpty_input", str(value)) from value
        return value

    def get_size() -> tuple[int, int]:
        info = SCREEN()
        check(screen_info(output_handle, c.byref(info)))
        left, top, right, bottom = info.window
        return right - left + 1, bottom - top + 1

    thread: threading.Thread | None = None
    try:
        check(set_mode(output_handle, output_mode.value | 4))  # VT output
        check(set_mode(input_handle, (input_mode.value & ~(1 | 2 | 4 | 0x40)) | 0x280))
        thread = threading.Thread(target=read_host, daemon=True)
        thread.start()
        return run_session(context, capture, stdout, read_input=read_input, get_size=get_size)
    except OSError as exc:
        raise RunnerError("conpty", str(exc)) from exc
    finally:
        stop.set()
        if thread is not None:
            if thread.native_id is not None:
                cancel_thread(thread.native_id)
            thread.join(0.5)
        # Restore modes even after a launch, forwarding or cleanup failure.
        restored_input = set_mode(input_handle, input_mode)
        restored_output = set_mode(output_handle, output_mode)
        if not restored_input or not restored_output:
            raise RunnerError("cleanup", "Could not restore Windows console modes")
        if thread is not None and thread.is_alive():
            raise RunnerError("cleanup", "Could not cancel Windows console input")
