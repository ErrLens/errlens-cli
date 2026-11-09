"""Disposable ConPTY owner. stdin/stdout carry a private bounded binary protocol."""

import json
import queue
import struct
import sys
import threading
import time
from typing import BinaryIO

MAX_FRAME = 65536


def receive(stream: BinaryIO) -> tuple[bytes, bytes]:
    def exact(size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = stream.read(size - len(data))
            if not chunk:
                raise EOFError("ConPTY transport closed")
            data.extend(chunk)
        return bytes(data)
    kind, size = struct.unpack("!cI", exact(5))
    if size > MAX_FRAME:
        raise ValueError("ConPTY frame exceeds limit")
    return kind, exact(size)


def send(stream: BinaryIO, kind: bytes, data: bytes = b"") -> None:
    if len(data) > MAX_FRAME:
        raise ValueError("ConPTY frame exceeds limit")
    view = memoryview(struct.pack("!cI", kind, len(data)) + data)
    while view:
        count = stream.write(view)
        if count is None or count <= 0:
            raise OSError("ConPTY transport made no progress")
        view = view[count:]
    stream.flush()


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    import os
    from ctypes import wintypes as w
    from errlens._conpty import api, check, close_handle, Session, wait
    session = Session()
    controls: queue.Queue[tuple[bytes, bytes]] = queue.Queue(16)
    inputs: queue.Queue[bytes] = queue.Queue(16)
    failure: queue.SimpleQueue[Exception] = queue.SimpleQueue()
    stop = threading.Event()
    # If the frontend is killed (e.g. outer test timeout), do not leave this
    # owner or its clients behind, even while a native API is blocked.
    parent = api("OpenProcess", w.HANDLE, [w.DWORD, w.BOOL, w.DWORD])(0x100000, False, os.getppid())
    check(parent)

    def watch_parent() -> None:
        try:
            while not stop.is_set():
                if wait(parent, 100) != 258:
                    os._exit(125)  # the kill-on-close job owns clients from birth
        finally:
            close_handle(parent)
    watcher = threading.Thread(target=watch_parent, daemon=True)
    watcher.start()

    def read_controls() -> None:
        try:
            while not stop.is_set():
                item = receive(sys.stdin.buffer)
                while not stop.is_set():
                    try:
                        controls.put(item, timeout=0.05)
                        break
                    except queue.Full:
                        pass
        except Exception as exc:
            failure.put(exc)

    def write_input() -> None:
        try:
            while not stop.is_set():
                try:
                    session.write(inputs.get(timeout=0.05))
                except queue.Empty:
                    pass
        except Exception as exc:
            failure.put(exc)

    closer: threading.Thread | None = None
    try:
        kind, raw = receive(sys.stdin.buffer)
        if kind != b"C":
            raise ValueError("Expected ConPTY configuration")
        config = json.loads(raw)
        session.start(config["command"], config["cwd"], tuple(config["size"]))
        threading.Thread(target=read_controls, daemon=True).start()
        threading.Thread(target=write_input, daemon=True).start()
        send(sys.stdout.buffer, b"R")
        closing_at: float | None = None
        eof_at: float | None = None
        while True:
            data = session.read()
            if data:
                send(sys.stdout.buffer, b"O", data)
            if closer is None:
                status = session.status()
                if status is not None:
                    send(sys.stdout.buffer, b"S", struct.pack("!I", status))
                    stop.set()
                    closer = threading.Thread(target=session.close_pseudo_console, daemon=True)
                    closer.start()
                    closing_at = time.monotonic()
                else:
                    if data == b"":
                        if eof_at is None:
                            eof_at = time.monotonic()
                        elif time.monotonic() - eof_at > 1:
                            raise OSError("ConPTY output closed while client remained alive")
                    if not failure.empty():
                        raise failure.get()
                    if not inputs.full():
                        try:
                            kind, payload = controls.get_nowait()
                            if kind == b"I":
                                inputs.put_nowait(payload)
                            elif kind == b"W":
                                session.resize(struct.unpack("!HH", payload))
                            else:
                                raise ValueError("Unknown ConPTY control")
                        except queue.Empty:
                            pass
            elif not closer.is_alive() and data == b"":
                break
            elif closing_at is not None and time.monotonic() - closing_at > 2:
                raise TimeoutError("ConPTY close/drain exceeded two seconds")
            if not data:
                time.sleep(0.005)
        send(sys.stdout.buffer, b"D")
    except Exception as exc:
        code = 127 if isinstance(exc, FileNotFoundError) else 126 if isinstance(exc, PermissionError) else 125
        send(sys.stdout.buffer, b"E", json.dumps({"detail": str(exc)[:8192], "code": code}).encode("utf-8"))
    finally:
        stop.set()
        # The parent enforces the ultimate deadline even if this Windows API blocks.
        if closer is None:
            closer = threading.Thread(target=session.close_pseudo_console, daemon=True)
            closer.start()
        closer.join(2)
        if not closer.is_alive():
            session.close_handles()
        # Avoid Python's buffered-stdin shutdown lock held by the daemon reader.
        watcher.join(0.5)
        os._exit(0)


if __name__ == "__main__":
    main()
