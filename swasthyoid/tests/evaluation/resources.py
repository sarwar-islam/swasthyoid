"""Peak memory and CPU time of this process and the processes it starts, for the evaluation harness. Standard library only.

The OCR runner is a child process (the PaddleOCR adapter starts one per read), so a reading of this process alone would
miss it. What is measured differs by platform, and the report says which (`kind`):
- Windows: this process is put in a job object; children join it. peak_memory_bytes is the job's PeakProcessMemoryUsed
  (the largest committed memory of any one process in the job); cpu_seconds is user + kernel time of every process in the
  job, ended ones included.
- Linux and macOS: getrusage(RUSAGE_SELF) and (RUSAGE_CHILDREN) (children are counted once they have been waited for).
  peak_memory_bytes is the largest maximum resident set size of this process or of any waited-for child; cpu_seconds is
  user + system time of both.
Both include this harness process itself (small next to an OCR model). Differences of cpu_seconds between two readings
give the CPU used in between. None means the platform gave no reading; nothing is estimated.
"""
import sys

KIND_WINDOWS = "windows_job_peak_process_commit"
KIND_POSIX = "posix_rusage_max_rss"


class _Windows:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes, k = ctypes, ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                ctypes.c_void_p)
        self.kernel32 = k
        self.job = k.CreateJobObjectW(None, None)
        if not self.job or not k.AssignProcessToJobObject(self.job, k.GetCurrentProcess()):
            raise OSError("job object unavailable")

        class Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class Basic(ctypes.Structure):
            _fields_ = [("per_process_user", ctypes.c_longlong), ("per_job_user", ctypes.c_longlong),
                        ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
                        ("max_ws", ctypes.c_size_t), ("active_limit", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                        ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", Io), ("process_limit", ctypes.c_size_t),
                        ("job_limit", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [("user", ctypes.c_longlong), ("kernel", ctypes.c_longlong),
                        ("this_user", ctypes.c_longlong), ("this_kernel", ctypes.c_longlong),
                        ("page_faults", wintypes.DWORD), ("processes", wintypes.DWORD),
                        ("active", wintypes.DWORD), ("terminated", wintypes.DWORD)]

        self.Extended, self.Accounting = Extended, Accounting

    def _query(self, cls, info_class):
        value = cls()
        if not self.kernel32.QueryInformationJobObject(self.job, info_class, self.ctypes.byref(value),
                                                       self.ctypes.sizeof(value), None):
            raise OSError("job query failed")
        return value

    def read(self):
        accounting = self._query(self.Accounting, 1)  # JobObjectBasicAccountingInformation
        extended = self._query(self.Extended, 9)      # JobObjectExtendedLimitInformation
        return {"kind": KIND_WINDOWS, "peak_memory_bytes": int(extended.peak_process),
                "cpu_seconds": (accounting.user + accounting.kernel) / 1e7}  # 100-nanosecond units


class _Posix:
    def read(self):
        import resource
        scale = 1 if sys.platform == "darwin" else 1024  # ru_maxrss: bytes on macOS, kilobytes on Linux
        own, children = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
        return {"kind": KIND_POSIX, "peak_memory_bytes": max(own.ru_maxrss, children.ru_maxrss) * scale,
                "cpu_seconds": own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime}


class Meter:
    """Start once, before any child is started (on Windows this process then stays in the job for its life).
    read() returns {"kind", "peak_memory_bytes", "cpu_seconds"} or all None when the platform gives no reading."""

    def __init__(self):
        try:
            self._source = _Windows() if sys.platform == "win32" else _Posix()
            self._source.read()
        except (OSError, ImportError, AttributeError):
            self._source = None

    def read(self):
        if self._source is None:
            return {"kind": None, "peak_memory_bytes": None, "cpu_seconds": None}
        try:
            return self._source.read()
        except OSError:
            return {"kind": None, "peak_memory_bytes": None, "cpu_seconds": None}


if __name__ == "__main__":  # used by the tests: measure a child that holds N bytes, print the readings as JSON
    import json
    import subprocess
    meter = Meter()
    before = meter.read()
    subprocess.run([sys.executable, "-c", f"x = bytearray({int(sys.argv[1])}); sum(range(2_000_000))"], check=True)
    print(json.dumps({"before": before, "after": meter.read()}))
