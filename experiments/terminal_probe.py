"""Stage 7.1 research only. Run on POSIX in a separate process, not imported by CLI."""

import errno
import fcntl
import json
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import time


def main() -> None:
    code = "import sys,os; print([s.isatty() for s in (sys.stdin,sys.stdout,sys.stderr)],flush=True); print(input('input:')); os.write(1,b'\\x00\\xff\\n'); os.write(2,b'\\x1b[31mred\\x1b[0m'); sys.exit(7)"
    pipe = subprocess.run([sys.executable, "-m", "errlens", "run", "--no-explain", "--", sys.executable, "-c", code],
                          input=b"answer\n", capture_output=True, timeout=10)
    print(json.dumps({"mode": "actual pipe runner", "exit": pipe.returncode,
                      "stdout": repr(pipe.stdout), "stderr": repr(pipe.stderr)}))
    child = """import os,sys,signal,time
print('TTY',*[s.isatty() for s in (sys.stdin,sys.stdout,sys.stderr)],flush=True)
fd=os.open('/dev/tty',os.O_RDWR);os.close(fd)
signal.signal(signal.SIGWINCH,lambda *_:print('SIZE',os.get_terminal_size(0),flush=True))
signal.signal(signal.SIGINT,lambda *_:sys.exit(23))
print('READY',flush=True)
print('ANSWER',input(),flush=True)
os.write(1,b'\\x00\\xff\\n');os.write(2,b'\\x1b[31mred\\x1b[0m')
time.sleep(30)
"""
    pid, master = pty.fork()
    if pid == 0:
        os.execv(sys.executable, [sys.executable, "-c", child])
    output = bytearray()
    resized = interrupted = False
    status = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    chunk = os.read(master, 4096)
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    break
                if not chunk:
                    break
                output.extend(chunk)
            if b"READY" in output and not resized:
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 33, 101, 0, 0))
                os.write(master, b"answer\n")
                resized = True
            if b"ANSWER answer" in output and b"SIZE" in output and not interrupted:
                os.write(master, b"\x03")
                interrupted = True
            done, child_status = os.waitpid(pid, os.WNOHANG)
            if done:
                status = child_status
                break
        if status is None:
            done, child_status = os.waitpid(pid, os.WNOHANG)
            if done:
                status = child_status
        assert resized and interrupted and status is not None, repr(output)
        print(json.dumps({"mode": "experimental forkpty", "exit": os.waitstatus_to_exitcode(status),
                          "combined": repr(bytes(output)), "resize": resized, "ctrl_c_byte": interrupted}))
    finally:
        if status is None:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
        os.close(master)


if __name__ == "__main__":
    main()
