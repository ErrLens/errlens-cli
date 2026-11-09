"""Single-threaded POSIX session setup helper; no Python preexec_fn in parent."""

import os
import sys


def main() -> None:
    if sys.platform == "win32":
        raise RuntimeError("POSIX PTY helper is not available on Windows")
    import fcntl
    import termios

    error_fd = int(sys.argv[1])
    os.set_inheritable(error_fd, False)
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        os.tcsetpgrp(0, os.getpgrp())
        os.execvpe(sys.argv[2], sys.argv[2:], os.environ)
    except OSError as exc:
        os.write(error_fd, f"{exc.errno}: {exc}".encode("utf-8", errors="replace")[:4096])
        os._exit(127 if isinstance(exc, FileNotFoundError) else 126)


if __name__ == "__main__":
    main()
