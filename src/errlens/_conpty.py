"""Private Win32 bindings, imported only by the Windows terminal transport.

Session lives in a disposable helper process: ClosePseudoConsole has no timeout
on older Windows. Its job owns every client; no breakaway is enabled.
"""

import sys
import ctypes as c
from ctypes import wintypes as w
import os
import shutil
import subprocess
from typing import Any


class COORD(c.Structure):
    _fields_ = [("X", c.c_short), ("Y", c.c_short)]


class INFO(c.Structure):
    _fields_ = [("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR),
                ("title", w.LPWSTR), ("x", w.DWORD), ("y", w.DWORD),
                ("width", w.DWORD), ("height", w.DWORD), ("chars_x", w.DWORD),
                ("chars_y", w.DWORD), ("fill", w.DWORD), ("flags", w.DWORD),
                ("show", w.WORD), ("reserved_size", w.WORD), ("reserved_data", w.LPVOID),
                ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE)]


class INFOEX(c.Structure):
    _fields_ = [("info", INFO), ("attributes", w.LPVOID)]


class PROCESS(c.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE),
                ("pid", w.DWORD), ("tid", w.DWORD)]


class LIMITS(c.Structure):
    _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64),
                ("flags", w.DWORD), ("min_working_set", c.c_size_t),
                ("max_working_set", c.c_size_t), ("process_limit", w.DWORD),
                ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]


class JOBINFO(c.Structure):
    _fields_ = [("limits", LIMITS), ("io", c.c_uint64 * 6),
                ("process_memory", c.c_size_t), ("job_memory", c.c_size_t),
                ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]


class SCREEN(c.Structure):
    _fields_ = [("size", COORD), ("cursor", COORD), ("attributes", w.WORD),
                ("window", c.c_short * 4), ("maximum", COORD)]


_kernel: Any = None


def api(name: str, result: Any, args: list[Any]) -> Any:
    # Loading bindings is lazy too: module discovery must remain portable.
    function: Any = None
    def invoke(*values: Any) -> Any:
        nonlocal function
        global _kernel
        if sys.platform != "win32":
            raise OSError("Windows-only ConPTY API")
        if function is None:
            if _kernel is None:
                _kernel = c.WinDLL("kernel32", use_last_error=True)
            function = getattr(_kernel, name)
            function.restype, function.argtypes = result, args
        return function(*values)
    return invoke


close_handle = api("CloseHandle", w.BOOL, [w.HANDLE])
get_mode = api("GetConsoleMode", w.BOOL, [w.HANDLE, c.POINTER(w.DWORD)])
set_mode = api("SetConsoleMode", w.BOOL, [w.HANDLE, w.DWORD])
screen_info = api("GetConsoleScreenBufferInfo", w.BOOL, [w.HANDLE, c.POINTER(SCREEN)])
read_file = api("ReadFile", w.BOOL, [w.HANDLE, w.LPVOID, w.DWORD, c.POINTER(w.DWORD), w.LPVOID])
write_file = api("WriteFile", w.BOOL, [w.HANDLE, w.LPCVOID, w.DWORD, c.POINTER(w.DWORD), w.LPVOID])
peek = api("PeekNamedPipe", w.BOOL, [w.HANDLE, w.LPVOID, w.DWORD, w.LPVOID,
                                     c.POINTER(w.DWORD), w.LPVOID])
wait = api("WaitForSingleObject", w.DWORD, [w.HANDLE, w.DWORD])
terminate_job = api("TerminateJobObject", w.BOOL, [w.HANDLE, w.UINT])


def check(value: Any) -> None:
    if not value:
        raise win_error()


def last_error() -> int:
    if sys.platform == "win32":
        return c.get_last_error()
    raise OSError("Windows-only ConPTY API")


def win_error() -> OSError:
    if sys.platform == "win32":
        return c.WinError(c.get_last_error())
    return OSError("Windows-only ConPTY API")


def cancel_thread(native_id: int) -> None:
    handle = api("OpenThread", w.HANDLE, [w.DWORD, w.BOOL, w.DWORD])(1, False, native_id)
    if handle:
        try:
            api("CancelSynchronousIo", w.BOOL, [w.HANDLE])(handle)
        finally:
            close_handle(handle)


class Session:
    def __init__(self) -> None:
        self.handles: list[int] = []
        self.hpc: int | None = None
        self.process = self.job = self.input = self.output = 0

    def own(self, handle: int) -> int:
        check(handle)
        self.handles.append(handle)
        return handle

    def release(self, handle: int) -> None:
        self.handles.remove(handle)
        check(close_handle(handle))

    def start(self, command: list[str], cwd: str, size: tuple[int, int]) -> None:
        executable = shutil.which(command[0])
        if executable is None:
            raise FileNotFoundError(2, "Executable not found", command[0])
        # CreateProcess must not implicitly dispatch batch files through cmd.exe.
        if os.path.splitext(executable)[1].lower() not in {".exe", ".com"}:
            raise OSError("ConPTY requires a native executable (.exe or .com)")
        pipe = api("CreatePipe", w.BOOL, [c.POINTER(w.HANDLE), c.POINTER(w.HANDLE), w.LPVOID, w.DWORD])
        def make_pipe() -> tuple[int, int]:
            left, right = w.HANDLE(), w.HANDLE()
            check(pipe(c.byref(left), c.byref(right), None, 0))
            assert left.value is not None and right.value is not None
            return self.own(left.value), self.own(right.value)
        read_input, self.input = make_pipe()
        self.output, write_output = make_pipe()
        create = api("CreatePseudoConsole", c.c_long,
                     [COORD, w.HANDLE, w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)])
        hpc = w.HANDLE()
        result = create(COORD(*size), read_input, write_output, 0, c.byref(hpc))
        if result < 0:
            raise OSError(f"CreatePseudoConsole failed: HRESULT 0x{result & 0xffffffff:08x}")
        self.hpc = hpc.value
        self.release(read_input)
        self.release(write_output)
        self.job = self.own(api("CreateJobObjectW", w.HANDLE, [w.LPVOID, w.LPCWSTR])(None, None))
        limits = JOBINFO()
        limits.limits.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        check(api("SetInformationJobObject", w.BOOL, [w.HANDLE, c.c_int, w.LPVOID, w.DWORD])(
            self.job, 9, c.byref(limits), c.sizeof(limits)))
        initialize = api("InitializeProcThreadAttributeList", w.BOOL,
                         [w.LPVOID, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)])
        length = c.c_size_t()
        initialize(None, 2, 0, c.byref(length))
        attributes = c.create_string_buffer(length.value)
        check(initialize(attributes, 2, 0, c.byref(length)))
        try:
            check(api("UpdateProcThreadAttribute", w.BOOL,
                      [w.LPVOID, w.DWORD, c.c_size_t, w.LPVOID, c.c_size_t, w.LPVOID, w.LPVOID])(
                          attributes, 0, 0x20016, self.hpc, c.sizeof(w.HANDLE), None, None))
            jobs = (w.HANDLE * 1)(self.job)
            # Assign at creation, avoiding an orphan if the owner dies between
            # CreateProcess and AssignProcessToJobObject/ResumeThread.
            check(api("UpdateProcThreadAttribute", w.BOOL,
                      [w.LPVOID, w.DWORD, c.c_size_t, w.LPVOID, c.c_size_t, w.LPVOID, w.LPVOID])(
                          attributes, 0, 0x2000d, jobs, c.sizeof(jobs), None, None))
            info, process = INFOEX(), PROCESS()
            info.info.cb = c.sizeof(info)
            # Null standard handles with this flag prevent redirected owner pipes
            # from leaking into the client instead of its pseudoconsole handles.
            info.info.flags = 0x100  # STARTF_USESTDHANDLES
            info.attributes = c.cast(attributes, w.LPVOID)
            argv = c.create_unicode_buffer(subprocess.list2cmdline([executable, *command[1:]]))
            check(api("CreateProcessW", w.BOOL, [w.LPCWSTR, w.LPWSTR, w.LPVOID, w.LPVOID,
                      w.BOOL, w.DWORD, w.LPVOID, w.LPCWSTR, c.POINTER(INFOEX), c.POINTER(PROCESS)])(
                          executable, argv, None, None, False, 0x80000, None, cwd,
                          c.byref(info), c.byref(process)))
            self.process = self.own(process.process)
            thread = self.own(process.thread)
            self.release(thread)
        finally:
            api("DeleteProcThreadAttributeList", None, [w.LPVOID])(attributes)

    def resize(self, size: tuple[int, int]) -> None:
        result = api("ResizePseudoConsole", c.c_long, [w.HANDLE, COORD])(self.hpc, COORD(*size))
        if result < 0:
            raise OSError(f"ResizePseudoConsole failed: {result}")

    def status(self) -> int | None:
        result = wait(self.process, 0)
        if result == 258:
            return None
        if result != 0:
            raise win_error()
        code = w.DWORD()
        check(api("GetExitCodeProcess", w.BOOL, [w.HANDLE, c.POINTER(w.DWORD)])(self.process, c.byref(code)))
        return code.value

    def read(self) -> bytes | None:
        available = w.DWORD()
        if not peek(self.output, None, 0, None, c.byref(available), None):
            if last_error() in (109, 232):
                return b""
            raise win_error()
        if not available.value:
            return None
        data, count = c.create_string_buffer(min(available.value, 65536)), w.DWORD()
        check(read_file(self.output, data, len(data), c.byref(count), None))
        return data.raw[:count.value]

    def write(self, data: bytes) -> None:
        while data:
            count = w.DWORD()
            check(write_file(self.input, data, len(data), c.byref(count), None))
            if count.value == 0:
                raise OSError("ConPTY input made no progress")
            data = data[count.value:]

    def close_pseudo_console(self) -> None:
        if self.job:
            terminate_job(self.job, 125)
        hpc, self.hpc = self.hpc, None
        if hpc:
            api("ClosePseudoConsole", None, [w.HANDLE])(hpc)

    def close_handles(self) -> None:
        for handle in reversed(self.handles):
            close_handle(handle)
        self.handles.clear()
