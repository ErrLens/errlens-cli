"""Real ConPTY, including headless CI and a nested console for the CLI frontend.

Every scenario runs in its own process with an outer timeout. No user console,
profile or output log is touched. Run this file directly only via the harness.
"""

import base64
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows ConPTY")


@pytest.fixture
def probe(tmp_path):
    def execute(scenario):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), scenario, str(tmp_path)],
                                capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        data = json.loads(result.stdout)
        data["output"] = base64.b64decode(data["output"])
        return data
    return execute


def test_three_ttys_input_unicode_ansi_argv_cwd_and_exit_code(probe):
    data = probe("interactive")
    assert data["status"] == 7
    assert b"True, True, True" in data["output"]
    assert "Привет 🌍".encode() in data["output"]
    assert b"two words" in data["output"] and b'with "quotes"' in data["output"]
    assert "путь с пробелами".encode() in data["output"]
    assert b"\x1b[31m" in data["output"] and b"RED" in data["output"]


def test_resize_is_visible_to_child(probe):
    data = probe("resize")
    assert data["status"] == 0
    assert b"columns=80, lines=24" in data["output"]
    assert b"columns=101, lines=33" in data["output"]


def test_ctrl_c_targets_child_and_preserves_handled_status(probe):
    data = probe("interrupt")
    assert data["status"] == 23
    assert b"READY" in data["output"]


def test_binary_output_is_terminal_text_not_a_binary_pipe(probe):
    data = probe("binary")
    assert data["status"] == 0 and b"BINARY-END" in data["output"]
    assert len(data["output"]) < 4096


@pytest.mark.parametrize("case", ["traceback-ru", "traceback-en", "no-explain", "success"])
def test_real_cli_and_explanation_policy(probe, case):
    data = probe(case)
    # ConPTY may insert VT cursor/color/title sequences inside displayed text.
    output = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]",
                    "", data["output"].decode("utf-8", errors="replace"))
    assert data["status"] == (0 if case == "success" else 1)
    if case == "success":
        assert "SUCCESS" in output and "ErrLens" not in output
    else:
        assert output.count("Traceback (most recent call last):") == 1
        if case == "no-explain":
            assert "ErrLens" not in output
        else:
            phrase = "Имя не определено" if case.endswith("ru") else "Undefined name"
            if phrase not in output:
                # pytest abbreviates string diffs; retain the entire transport
                # transcript in captured stdout for CI diagnosis, including VT.
                print(json.dumps({"case": case, "status": data["status"],
                                  "python": sys.version, "terminal_size": [80, 24],
                                  "raw_utf8": data["output"].decode("utf-8", errors="replace"),
                                  "raw_base64": base64.b64encode(data["output"]).decode("ascii")},
                                 ensure_ascii=True))
            assert phrase in output


def test_cleanup_bounded_capture_handle_and_thread_counts(probe):
    data = probe("cleanup")
    assert data["status"] == 0


def test_transport_failure_does_not_retry_and_kills_descendants(probe):
    assert probe("failure")["status"] == 125


def test_launch_failure_cleanup_and_exit_code(probe):
    assert probe("launch-error")["status"] == 127


def test_console_modes_restored_on_success_and_failure(probe):
    data = probe("modes")
    assert data["status"] == 0 and b"MODES-RESTORED" in data["output"]


def test_powershell_7_invokes_opt_in_cli(probe):
    if shutil.which("pwsh") is None:
        pytest.skip("PowerShell 7 is unavailable")
    data = probe("powershell")
    assert data["status"] == 0 and b"PS-STATUS 9" in data["output"]


def test_cli_ctrl_c_suppresses_explanation(probe):
    data = probe("cli-interrupt")
    assert data["status"] == 130 and b"KeyboardInterrupt" in data["output"]
    assert b"Error detected" not in data["output"]


def test_explanation_is_written_to_redirected_stderr(probe):
    data = probe("stderr")
    assert data["status"] == 1 and b"STDERR-CARD-VERIFIED" in data["output"]


@pytest.mark.parametrize("status", [0, 259, 0x80000001])
def test_windows_dword_exit_status(probe, status):
    assert probe(f"status-{status}")["status"] == status


@pytest.mark.parametrize("case", ["external-interrupt", "flood-interrupt"])
def test_external_interrupt_has_bounded_tree_cleanup(probe, case):
    data = probe(case)
    assert data["interrupted"] is True and data["elapsed"] < 6


def scenario(name: str, directory: Path) -> dict:
    """Runs in a disposable Python process, never the pytest runner's console."""
    import ctypes as c
    from ctypes import wintypes as w
    import threading
    from errlens._conpty import api, check, close_handle, wait
    from errlens.capture import TerminalCapture
    from errlens.conpty_runner import run_session
    from errlens.models import ExecutionContext
    from errlens.runner import RunnerError
    out = io.BytesIO()
    capture = TerminalCapture()
    cwd = directory / "путь с пробелами"
    cwd.mkdir()
    command = [sys.executable, "-c"]
    size = (80, 24)
    answer = None
    if name == "interactive":
        command += ["import sys,os; print([s.isatty() for s in (sys.stdin,sys.stdout,sys.stderr)],flush=True); "
                    "print(sys.argv[1:],os.getcwd(),flush=True); print('READY',flush=True); print(input(),flush=True); "
                    "os.write(2,b'\\x1b[31mRED\\x1b[0m'); sys.exit(7)", "two words", 'with "quotes"']
        answer = "Привет 🌍\r".encode()
    elif name == "resize":
        command += ["import os,time; print('INITIAL',os.get_terminal_size(),flush=True); print('READY',flush=True); "
                    "\nwhile os.get_terminal_size().columns != 101: time.sleep(.02)"
                    "\nprint('RESIZED',os.get_terminal_size(),flush=True)"]
    elif name == "interrupt":
        command += ["import signal,sys,time; signal.signal(signal.SIGINT,lambda *_:sys.exit(23)); "
                    "print('READY',flush=True); time.sleep(20)"]
        answer = b"\x03"
    elif name == "cli-interrupt":
        command = [sys.executable, "-m", "errlens", "run", "--terminal-mode", "pty", "--",
                   sys.executable, "-c", "import time;print('READY',flush=True);time.sleep(20)"]
        answer = b"\x03"
    elif name.startswith("status-"):
        status = int(name.split('-')[1])
        command += [f"import os;os._exit({status if status < 2**31 else status - 2**32})"]
    elif name in {"external-interrupt", "flood-interrupt"}:
        import signal
        start = time.monotonic()
        timer = None
        def interrupt():
            nonlocal timer
            if b"READY" in out.getvalue():
                if name == "external-interrupt":
                    signal.raise_signal(signal.SIGINT)
                else:
                    if timer is None:
                        timer = threading.Timer(1, lambda: signal.raise_signal(signal.SIGINT))
                        timer.start()
                    return b"x" * 4096
            return None
        result = run_session(ExecutionContext([sys.executable, "-c",
            "import signal,time;signal.signal(signal.SIGINT,signal.SIG_IGN);print('READY',flush=True);time.sleep(60)"], str(cwd)),
            capture, out, read_input=interrupt)
        return {"status": result.exit_code, "interrupted": result.interrupted,
                "elapsed": time.monotonic() - start, "output": ""}
    elif name == "binary":
        command += ["import os;os.write(1,b'\\x00\\xff\\nBINARY-END\\n')"]
    elif name in {"traceback-ru", "traceback-en", "no-explain", "success"}:
        language = "en" if name == "traceback-en" else "ru"
        command = [sys.executable, "-m", "errlens", "run", "--terminal-mode", "pty", "--lang", language]
        if name == "no-explain":
            command += ["--no-explain"]
        command += ["--", sys.executable, "-c", "print('SUCCESS')" if name == "success" else "print(undefined_variable)"]
    elif name == "modes":
        code = """import ctypes as c,msvcrt,sys,os
from ctypes import wintypes as w
from errlens._conpty import get_mode
from errlens.conpty_runner import run
from errlens.capture import TerminalCapture
from errlens.models import ExecutionContext
from errlens.runner import RunnerError
import threading
def modes():
    values=[]
    for fd in (0,1):
        value=w.DWORD(); assert get_mode(msvcrt.get_osfhandle(fd),c.byref(value)); values.append(value.value)
    return values
before=modes()
threads=threading.active_count()
context=ExecutionContext([sys.executable,'-c',"print('OK')"],os.getcwd())
assert run(context,TerminalCapture(),sys.stdout.buffer).exit_code==0
assert modes()==before
assert threading.active_count()==threads
class Broken:
    def fileno(self): return 1
    def write(self,data): raise OSError('failed-output')
    def flush(self): pass
try: run(context,TerminalCapture(),Broken())
except RunnerError: pass
else: raise AssertionError('expected failure')
assert modes()==before
assert threading.active_count()==threads
print('MODES-RESTORED',flush=True)
"""
        command += [code]
    elif name == "stderr":
        inner = [sys.executable, "-m", "errlens", "run", "--terminal-mode", "pty", "--lang", "en", "--",
                 sys.executable, "-c", "print(undefined_variable)"]
        command += ["import subprocess,sys; p=subprocess.run(" + repr(inner) + ",stderr=subprocess.PIPE,timeout=15); "
                    "assert p.returncode==1; assert b'Undefined name' in p.stderr; "
                    "print('STDERR-CARD-VERIFIED');sys.exit(1)"]
    elif name == "powershell":
        # No profile loading, no global changes. All paths are quoted as PS literals.
        quote = lambda value: "'" + value.replace("'", "''") + "'"
        script = "& " + quote(sys.executable) + " -m errlens run --terminal-mode pty -- " + quote(sys.executable) + " -c 'import sys;sys.exit(9)'; Write-Output \"PS-STATUS $LASTEXITCODE\""
        command = [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script]
    elif name == "cleanup":
        count_handles = api("GetProcessHandleCount", w.BOOL, [w.HANDLE, c.POINTER(w.DWORD)])
        def count():
            value = w.DWORD()
            check(count_handles(w.HANDLE(-1), c.byref(value)))
            return value.value
        # Python initializes wait/signal machinery on the first threaded spawn.
        run_session(ExecutionContext([sys.executable, "-c", "pass"], str(cwd)), capture, out)
        before, threads = count(), threading.active_count()
        for _ in range(4):
            tail = TerminalCapture(16)
            result = run_session(ExecutionContext([sys.executable, "-c", "print('x'*1000)"], str(cwd)), tail, io.BytesIO())
            assert result.exit_code == 0 and not result.output_complete
            assert len(tail.combined.data) == 16
        assert count() == before, (before, count())
        assert threading.active_count() == threads
        return {"status": 0, "output": ""}
    elif name == "failure":
        marker = directory / "executions"
        pids = directory / "pids"
        code = ("import os,sys,subprocess,time; "
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
                f"open({str(pids)!r},'w').write(str(os.getpid())+','+str(p.pid)); "
                f"open({str(marker)!r},'a').write('x'); print('READY',flush=True); time.sleep(60)")
        class Broken:
            def write(self, data):
                out.write(data)
                if b"READY" in out.getvalue():
                    raise OSError("test-output-failure")
                return len(data)
            def flush(self):
                pass
        try:
            run_session(ExecutionContext([sys.executable, "-c", code], str(cwd)), capture, Broken())
        except RunnerError as exc:
            assert "test-output-failure" in str(exc)
        else:
            raise AssertionError("Expected transport failure")
        assert marker.read_text() == "x"
        for pid in map(int, pids.read_text().split(",")):
            handle = api("OpenProcess", w.HANDLE, [w.DWORD, w.BOOL, w.DWORD])(0x100000, False, pid)
            if handle:
                try:
                    assert wait(handle, 3000) == 0, f"Leaked child {pid}"
                finally:
                    close_handle(handle)
        return {"status": 125, "output": ""}
    elif name == "launch-error":
        for context, code in [(ExecutionContext(["errlens-no-such-executable-987.exe"], str(cwd)), 127),
                              (ExecutionContext([sys.executable, "-c", "pass"], str(cwd / "missing")), 125)]:
            try:
                run_session(context, capture, out)
            except RunnerError as exc:
                assert exc.exit_code == code
            else:
                raise AssertionError("Expected launch failure")
        return {"status": 127, "output": ""}
    else:
        raise AssertionError(name)

    sent = False
    def read_input():
        nonlocal sent
        if answer and not sent and b"READY" in out.getvalue():
            sent = True
            return answer
        return None
    def get_size():
        if name == "resize" and b"READY" in out.getvalue():
            return 101, 33
        return size
    result = run_session(ExecutionContext(command, str(cwd)), capture, out,
                         read_input=read_input, get_size=get_size)
    return {"status": result.exit_code, "output": base64.b64encode(out.getvalue()).decode("ascii")}


if __name__ == "__main__":
    sys.stdout.buffer.write(json.dumps(scenario(sys.argv[1], Path(sys.argv[2]))).encode("utf-8"))
