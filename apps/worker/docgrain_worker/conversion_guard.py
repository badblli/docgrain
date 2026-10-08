"""One disposable process per conversion, including source verification/decoding."""

from __future__ import annotations

import math
import multiprocessing
import os
import pickle
import time
from pathlib import Path
from tempfile import TemporaryDirectory


class WorkerCrash(RuntimeError):
    """The bounded child crashed, exceeded its budget or returned no result."""


class ConversionError(RuntimeError):
    """The child stopped with an ordinary error (bad format, parser error).

    Same message the in-process parser used to persist; not a crash.
    """


def memory_limit(byte_limit):
    if os.name != "nt":
        import resource
        # RLIMIT_DATA counts committed private memory. RLIMIT_AS would also count the
        # large virtual reservations of Torch/ONNX/OpenMP and stop ordinary conversions.
        resource.setrlimit(resource.RLIMIT_DATA, (byte_limit, byte_limit))
        try:
            # If the host still runs out of memory, the kernel kills this child, not the worker.
            Path("/proc/self/oom_score_adj").write_text("1000")
        except OSError:
            pass
        return None
    # A Windows Job Object is a hard process memory limit and owns OCR descendants.
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class Io(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in
                    ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                     "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000 | 0x200  # kill-on-close, aggregate job memory
    info.JobMemoryLimit = byte_limit
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError("cannot install child memory limit")
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        raise OSError("cannot assign child memory limit")
    return handle  # OS owns it until process exit; do not close while the child is alive.


def _child(target, args, output, byte_limit):
    if os.name != "nt":
        os.setsid()  # Terminating the conversion also terminates its Tesseract children.
    memory_handle = memory_limit(byte_limit)
    try:
        try:
            value = ("ok", target(*args))
        except MemoryError:
            os._exit(3)
        except Exception as exc:  # noqa: BLE001 - message only; no child traceback crosses over.
            value = ("error", str(exc)[:1000])
        with open(output, "wb") as stream:
            pickle.dump(value, stream, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:  # noqa: BLE001 - an unserializable result is a failed conversion.
        os._exit(1)
    # Keep the Windows Job handle live through serialization.
    del memory_handle


def _terminate(process):
    if os.name != "nt":
        import signal
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            # A timeout can fire while spawn is importing, before setsid().
            if process.is_alive():
                process.kill()
    elif process.is_alive():
        process.kill()
    process.join(timeout=5)


def isolated_call(target, args=(), *, timeout=None, memory_mb=None, tick=None):
    timeout = float(timeout if timeout is not None else os.getenv("DOCGRAIN_CONVERSION_TIMEOUT_SECONDS", "600"))
    memory_mb = int(memory_mb if memory_mb is not None else os.getenv("DOCGRAIN_CONVERSION_MEMORY_MB", "4096"))
    if not math.isfinite(timeout) or timeout <= 0 or memory_mb <= 0:
        raise ValueError("conversion limits must be positive")
    with TemporaryDirectory(prefix="docgrain-conversion-") as directory:
        output = Path(directory) / "result.pickle"
        byte_limit = memory_mb * 1024 * 1024
        if os.name != "nt":
            # Leave room for the supervising worker in a memory-limited container.
            for maximum, current in [("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current"),
                                     ("/sys/fs/cgroup/memory/memory.limit_in_bytes", "/sys/fs/cgroup/memory/memory.usage_in_bytes")]:
                try:
                    available = int(Path(maximum).read_text()) - int(Path(current).read_text()) - 256 * 1024 * 1024
                    byte_limit = min(byte_limit, max(1, available))
                    break
                except (OSError, ValueError):
                    continue
        process = multiprocessing.get_context("spawn").Process(
            target=_child, args=(target, args, output, byte_limit))
        started = time.monotonic()
        try:
            process.start()
            while process.is_alive():
                process.join(timeout=min(1, timeout))
                if tick:
                    tick()
                if time.monotonic() - started > timeout:
                    raise WorkerCrash("Belge okuma süresi sınırı aşıldı.")
            if process.exitcode != 0 or not output.exists():
                raise WorkerCrash("Belgeyi okuyan işlem beklenmedik biçimde durdu.")
            # Do not move an unbounded serialized document back into the worker loop.
            if output.stat().st_size > byte_limit // 4:
                raise WorkerCrash("Belge okuma sonucu bellek sınırını aştı.")
            with output.open("rb") as stream:
                kind, value = pickle.load(stream)  # Only this private, local child writes the file.
            if kind == "error":
                raise ConversionError(value)
            return value
        finally:
            if process.pid:
                _terminate(process)
            process.close()


def _parse(source, source_format):
    from .structural import DocumentParser
    return DocumentParser().parse(source, source_format)


def convert(source, source_format, *, tick=None):
    return isolated_call(_parse, (source, source_format), tick=tick)
