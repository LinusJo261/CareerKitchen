"""Bounded, isolated draft extraction after the caller's real malware scan.

This is process/resource isolation, not a complete operating-system sandbox. The
child has no application imports or credentials and never follows document URLs.
"""

from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass(frozen=True)
class ExtractionLimits:
    input_bytes: int = 10_000_000
    pages: int = 20
    uncompressed_bytes: int = 20_000_000
    output_chars: int = 25_000
    output_bytes: int = 200_000
    wall_seconds: float = 5.0
    cpu_seconds: int = 3
    memory_mb: int = 256

    def __post_init__(self) -> None:
        if not (
            1 <= self.input_bytes <= 10_000_000
            and 1 <= self.pages <= 100
            and 1024 <= self.uncompressed_bytes <= 30_000_000
            and 1 <= self.output_chars <= 25_000
            and 64 <= self.output_bytes <= 200_000
            and 0.01 <= self.wall_seconds <= 10
            and 1 <= self.cpu_seconds <= 5
            and 64 <= self.memory_mb <= 512
        ):
            raise ValueError("document extraction limits exceed supported bounds")


def _windows_job(process: subprocess.Popen[bytes], limits: ExtractionLimits) -> Any:
    """Apply a real Windows process memory/CPU/child-process limit before input."""
    import ctypes as ct
    from ctypes import wintypes as wt

    class Basic(ct.Structure):
        _fields_ = [
            ("process_time", ct.c_longlong),
            ("job_time", ct.c_longlong),
            ("flags", wt.DWORD),
            ("min_working_set", ct.c_size_t),
            ("max_working_set", ct.c_size_t),
            ("active_process_limit", wt.DWORD),
            ("affinity", ct.c_size_t),
            ("priority", wt.DWORD),
            ("scheduling", wt.DWORD),
        ]

    class Counters(ct.Structure):
        _fields_ = [
            (name, ct.c_ulonglong)
            for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")
        ]

    class Extended(ct.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io", Counters),
            ("process_memory", ct.c_size_t),
            ("job_memory", ct.c_size_t),
            ("peak_process_memory", ct.c_size_t),
            ("peak_job_memory", ct.c_size_t),
        ]

    load_library = getattr(ct, "WinDLL", None)
    if load_library is None:
        raise OSError("Windows job restrictions unavailable on this platform")
    kernel = load_library("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = [ct.c_void_p, wt.LPCWSTR], wt.HANDLE
    kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD]
    kernel.SetInformationJobObject.restype = wt.BOOL
    kernel.AssignProcessToJobObject.argtypes, kernel.AssignProcessToJobObject.restype = (
        [wt.HANDLE, wt.HANDLE],
        wt.BOOL,
    )
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [wt.HANDLE], wt.BOOL
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise OSError("document job unavailable")
    info = Extended()
    info.basic.flags = 0x00000002 | 0x00000008 | 0x00000100 | 0x00002000
    info.basic.process_time = limits.cpu_seconds * 10_000_000
    info.basic.active_process_limit = 1
    info.process_memory = limits.memory_mb * 1024 * 1024
    if not kernel.SetInformationJobObject(
        job, 9, ct.byref(info), ct.sizeof(info)
    ) or not kernel.AssignProcessToJobObject(job, wt.HANDLE(int(process._handle))):  # type: ignore[attr-defined]
        kernel.CloseHandle(job)
        raise OSError("document job restrictions unavailable")
    return lambda: kernel.CloseHandle(job)


def extract_document_text(
    content: bytes, mime: str, limits: ExtractionLimits = ExtractionLimits()
) -> str | None:
    """Return untrusted proposed text, or None on timeout, limits, unsupported/image PDF.

    The caller must finish validation and malware scanning first. A failed extractor
    never bypasses a failed scanner or upgrades a claim/profile to verified status.
    """
    import json

    mime = mime.split(";", 1)[0].strip().lower()
    if mime not in (PDF, DOCX) or not content or len(content) > limits.input_bytes:
        return None
    child = Path(__file__).with_name("extraction_child.py").resolve()
    args = [
        getattr(sys, "_base_executable", sys.executable),
        "-I",
        "-B",
        "-u",
        str(child),
        mime,
        str(limits.input_bytes),
        str(limits.pages),
        str(limits.uncompressed_bytes),
        str(limits.output_chars),
        str(limits.cpu_seconds),
        str(limits.memory_mb),
        str(limits.output_bytes),
        sysconfig.get_path("purelib"),
    ]
    environment = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
    output = bytearray()
    exceeded = threading.Event()
    process: subprocess.Popen[bytes] | None = None
    close_job = None
    try:
        with tempfile.TemporaryDirectory(prefix="career-kitchen-extract-") as working:
            process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=working,
                env=environment,
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            if os.name == "nt":
                close_job = _windows_job(process, limits)
            current = process

            def read_output() -> None:
                assert current.stdout is not None
                while chunk := current.stdout.read(4096):
                    if len(output) + len(chunk) > limits.output_bytes:
                        exceeded.set()
                        current.kill()
                        return
                    output.extend(chunk)

            def write_input() -> None:
                assert current.stdin is not None
                try:
                    current.stdin.write(content)
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    current.stdin.close()

            reader = threading.Thread(target=read_output, daemon=True)
            writer = threading.Thread(target=write_input, daemon=True)
            reader.start()
            writer.start()
            process.wait(timeout=limits.wall_seconds)
            reader.join(timeout=0.5)
            writer.join(timeout=0.5)
            if process.returncode != 0 or exceeded.is_set() or reader.is_alive() or writer.is_alive():
                return None
            result = json.loads(output)
            text = result.get("text") if isinstance(result, dict) else None
            if not isinstance(text, str) or len(text) > limits.output_chars:
                return None
            return text or None
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None  # No raw document contents, parser diagnostics, or credentials in logs.
    finally:
        if process:
            if process.poll() is None:
                process.kill()
            process.wait()
            if close_job:
                close_job()
            for pipe in (process.stdin, process.stdout):
                if pipe:
                    pipe.close()
