"""Bounded merged logs and lifecycle ownership of real subprocess trees."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import threading
import time

MAX_LOG_BYTES = 1024 * 1024


class _WindowsJob:
    """A Job Object prevents descendants escaping when their parent exits first."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        class Basic(ctypes.Structure):
            _fields_ = [("ProcessTime", ctypes.c_longlong), ("JobTime", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSet", ctypes.c_size_t),
                        ("MaximumWorkingSet", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("IO", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def attach_and_resume(self, process):
        ctypes = self.ctypes
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        # Popen closes the primary thread handle. Resume the suspended process only
        # after assignment so no grandchild can race outside the Job Object.
        resume = ctypes.WinDLL("ntdll").NtResumeProcess
        resume.argtypes = [ctypes.c_void_p]
        resume.restype = ctypes.c_long
        if resume(int(process._handle)) != 0:
            raise OSError("Unable to resume managed process")

    def terminate(self):
        if self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def run_process(argv: list[str], cwd: Path, log_path: Path, timeout: float, cancel=None) -> dict:
    """Run argv without a shell; cancel may be an Event or a boolean callback."""
    if not argv or not all(isinstance(item, str) for item in argv):
        raise ValueError("argv must be a nonempty list of strings")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    start = time.monotonic()
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    def cancelled():
        return bool(cancel() if callable(cancel) else cancel.is_set()) if cancel is not None else False
    result = {"exit_code": None, "timed_out": False, "cancelled": False,
              "duration": 0.0, "log_truncated": False, "log_path": str(log_path)}
    with log_path.open("wb") as log:
        if cancelled():
            result.update(cancelled=True, duration=time.monotonic() - start)
            return result
        job = _WindowsJob() if os.name == "nt" else None
        process = None
        reader = None
        reader_errors = []
        def kill_tree():
            if job:
                job.terminate()
            elif process:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            process = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, creationflags=0x4 if job else 0,
                                       start_new_session=not bool(job))
            if job:
                job.attach_and_resume(process)
            def drain():
                written = 0
                try:
                    while True:
                        chunk = process.stdout.read(65536)
                        if not chunk:
                            break
                        remaining = MAX_LOG_BYTES - written
                        if remaining > 0:
                            piece = chunk[:remaining]
                            log.write(piece)
                            written += len(piece)
                        if len(chunk) > remaining:
                            result["log_truncated"] = True
                except OSError as error:
                    reader_errors.append(error)
            reader = threading.Thread(target=drain, name="gamebuild-log-drain", daemon=True)
            reader.start()
            while process.poll() is None:
                if cancelled():
                    result["cancelled"] = True
                    break
                if time.monotonic() - start >= timeout:
                    result["timed_out"] = True
                    break
                time.sleep(.02)
            # Also reap descendants after normal parent exit: no background work
            # can retain an inherited stdout pipe or mutate the workspace later.
            kill_tree()
            result["exit_code"] = process.wait(timeout=5)
            reader.join(timeout=5)
            if reader.is_alive():
                raise RuntimeError("subprocess log pipe did not close after tree termination")
            if reader_errors:
                raise reader_errors[0]
        finally:
            if process:
                kill_tree()
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                if reader:
                    reader.join(timeout=5)
                if process.stdout:
                    process.stdout.close()
            if job:
                job.close()
    result["duration"] = time.monotonic() - start
    return result
