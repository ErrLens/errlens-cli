"""Bounded cleanup and infrastructure failures, without analyzing diagnostics."""

import io
import signal
import sys
import threading
from pathlib import Path

import pytest

from errlens import runner
from errlens.capture import Capture
from errlens.models import ExecutionContext


def context(tmp_path: Path, code: str) -> ExecutionContext:
    return ExecutionContext([sys.executable, "-c", code], str(tmp_path))


def test_run_capture_and_cleanup(tmp_path: Path) -> None:
    capture, out, err = Capture(4), io.BytesIO(), io.BytesIO()
    result = runner.run(context(tmp_path, "import os; os.write(1,b'abcdef'); os.write(2,b'xyz')"),
                        capture, out, err)
    assert out.getvalue() == b"abcdef" and err.getvalue() == b"xyz"
    assert capture.stdout.data == b"cdef"
    assert result.exit_code == 0 and not result.output_complete
    assert not any(t.name.startswith("errlens-") for t in threading.enumerate())


@pytest.mark.parametrize("exception,kind,status", [
    (FileNotFoundError("missing"), "not_found", 127),
    (PermissionError("denied"), "permission", 126),
    (OSError("creation failed"), "launch", 125),
])
def test_launch_errors(exception, kind, status, tmp_path: Path,
                       monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise exception
    monkeypatch.setattr(runner.subprocess, "Popen", fail)
    with pytest.raises(runner.RunnerError) as caught:
        runner.run(context(tmp_path, "pass"), Capture(), io.BytesIO(), io.BytesIO())
    assert caught.value.kind == kind and caught.value.exit_code == status


@pytest.mark.parametrize("broken", [False, True])
def test_output_failure_cleans_up(tmp_path: Path, broken: bool) -> None:
    class FailedSink(io.BytesIO):
        def write(self, data):
            raise BrokenPipeError("closed") if broken else OSError("unwritable")
    with pytest.raises(runner.RunnerError) as caught:
        runner.run(context(tmp_path, "import os,time; os.write(1,b'x'); time.sleep(10)"),
                   Capture(), FailedSink(), io.BytesIO())
    assert caught.value.kind == ("broken_pipe" if broken else "write")
    assert not any(t.name.startswith("errlens-") for t in threading.enumerate())


def test_read_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(stream):
        raise OSError("read failed")
    monkeypatch.setattr(runner, "_available", fail)
    with pytest.raises(runner.RunnerError, match="read failed"):
        runner.run(context(tmp_path, "import time; time.sleep(10)"),
                   Capture(), io.BytesIO(), io.BytesIO())


def test_partial_writes(tmp_path: Path) -> None:
    class PartialSink(io.BytesIO):
        def write(self, data):
            return super().write(data[:2])
    output = PartialSink()
    runner.run(context(tmp_path, "import os; os.write(1,b'1234567')"),
               Capture(), output, io.BytesIO())
    assert output.getvalue() == b"1234567"


def test_eof_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Model a descendant holding an empty pipe open, without leaking a process.
    monkeypatch.setattr(runner, "_available", lambda source: 0)
    with pytest.raises(runner.RunnerError) as caught:
        runner.run(context(tmp_path, "pass"), Capture(), io.BytesIO(), io.BytesIO(),
                   drain_timeout=0.1)
    assert caught.value.kind == "drain"
    assert not any(t.name.startswith("errlens-") for t in threading.enumerate())


def test_cancellation_escalates_and_restores_handlers(tmp_path: Path) -> None:
    cancel = threading.Event()
    timer = threading.Timer(0.3, cancel.set)
    previous = signal.getsignal(signal.SIGINT)
    timer.start()
    try:
        result = runner.run(context(tmp_path, "import signal,time; signal.signal(signal.SIGINT,signal.SIG_IGN); "
                                   "signal.signal(signal.SIGBREAK,signal.SIG_IGN) if hasattr(signal,'SIGBREAK') else None; time.sleep(10)"),
                            Capture(), io.BytesIO(), io.BytesIO(), cancel=cancel,
                            interrupt_timeout=0.15)
    finally:
        timer.join()
    assert result.interrupted and result.exit_code != 0
    assert signal.getsignal(signal.SIGINT) == previous
    assert not any(t.name.startswith("errlens-") for t in threading.enumerate())
