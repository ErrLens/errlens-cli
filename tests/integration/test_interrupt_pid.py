"""Check the actual child's identity and death, not just ErrLens' exit code."""

import io
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

import pytest


@pytest.mark.parametrize("mode", ["pipe", "pty"])
def test_ctrl_c_real_child_pid(mode):
    if os.name != "nt" and not hasattr(os, "pidfd_open"):
        pytest.skip("Identity-safe PID check requires Windows handles or Linux pidfd (WSL)")
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), mode],
                            capture_output=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert b"CONFIRMED CHILD EXIT" in result.stdout
    print(result.stdout.decode("utf-8"), end="")


def probe(mode):
    token = uuid.uuid4().hex
    code = f"import os,time;print('CHILD',os.getpid(),'{token}',flush=True);time.sleep(60)"
    command = [sys.executable, "-m", "errlens", "run", "--terminal-mode", mode,
               "--", sys.executable, "-c", code]
    pattern = re.compile(rb"CHILD (\d+) " + token.encode())
    if os.name == "nt":
        from ctypes import wintypes as w
        from errlens._conpty import api, close_handle, wait
        from errlens.capture import TerminalCapture
        from errlens.conpty_runner import run_session
        from errlens.models import ExecutionContext
        output = io.BytesIO()
        handle = None
        child_pid = None
        def read_input():
            nonlocal handle, child_pid
            match = pattern.search(output.getvalue())
            if match and handle is None:
                child_pid = int(match[1])
                handle = api("OpenProcess", w.HANDLE, [w.DWORD, w.BOOL, w.DWORD])(0x100001, False, child_pid)
                assert handle, "Must acquire a handle while the real child is alive"
                assert wait(handle, 0) == 258, "Child exited before Ctrl+C"
                return b"\x03"
            return None
        try:
            result = run_session(ExecutionContext(command, os.getcwd()), TerminalCapture(), output,
                                 read_input=read_input, get_size=lambda: (120, 30))
            assert result.exit_code == 130, output.getvalue()
            assert handle is not None and wait(handle, 3000) == 0, "Actual child survived Ctrl+C"
            print("CONFIRMED CHILD EXIT", child_pid, mode)
        finally:
            if handle:
                # Cleanup on assertion failure cannot count as a successful check.
                if wait(handle, 0) == 258:
                    api("TerminateProcess", w.BOOL, [w.HANDLE, w.UINT])(handle, 125)
                close_handle(handle)
    else:
        import pty
        import select
        import signal
        import time
        master, slave = pty.openpty()
        process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=subprocess.PIPE,
                                   start_new_session=True)
        output = bytearray()
        pidfd = None
        child_pid = None
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if select.select([master], [], [], .05)[0]:
                    output.extend(os.read(master, 65536))
                match = pattern.search(output)
                if match and pidfd is None:
                    child_pid = int(match[1])
                    # pidfd pins the observed process identity; PID reuse cannot
                    # turn a dead or unrelated process into a successful result.
                    pidfd = os.pidfd_open(child_pid)
                    assert not select.select([pidfd], [], [], 0)[0], "Child already dead"
                    if mode == "pty":
                        os.write(master, b"\x03")
                    else:
                        os.kill(process.pid, signal.SIGINT)
                if process.poll() is not None:
                    break
            assert process.poll() == 130, (process.poll(), output)
            assert pidfd is not None and select.select([pidfd], [], [], 3)[0], "Actual child survived Ctrl+C"
            print("CONFIRMED CHILD EXIT", child_pid, mode)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
            if pidfd is not None:
                if not select.select([pidfd], [], [], 0)[0]:
                    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                os.close(pidfd)
            process.stderr.close()
            os.close(master)
            os.close(slave)


if __name__ == "__main__":
    probe(sys.argv[1])
