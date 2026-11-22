# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Windows: make sure sherpa-onnx runs on an ONNX Runtime that can serve it.

Windows 11 has its own ONNX Runtime as System32\\onnxruntime.dll. The Windows bundle renames
its copy to wm-onnxrt.dll (see packaging/bundle.py), so Windows can't hand over its own
instead. Running from source, nothing is renamed. When the worker starts, this checks which
copy sherpa-onnx actually got:
- its own: nothing to do;
- another copy that can't serve the API version sherpa-onnx was built for (an older one):
  sherpa-onnx would crash, so the job fails at once with a plain message;
- another copy that can (newer ones still serve older API versions): the job goes on, with
  a warning in its log.
"""

from __future__ import annotations

import ctypes
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

BUNDLED = "wm-onnxrt.dll"  # the bundle's renamed copy
PLAIN = "onnxruntime.dll"

UPDATE = "Updating Windows (Settings › Windows Update) and restarting may fix this."
REPORT = "copy the log and report it on the issues page"
FROM_SOURCE = " Or install WaveMaterial with its Windows installer, which isn't affected."
FAILED = (
    "WaveMaterial couldn't start its speech engine: Windows supplied an older copy of a "
    f"library it needs. {UPDATE} If it keeps happening, {REPORT}."
)
WARNING = (
    "Windows supplied its own copy of a library WaveMaterial needs. It should work, but if "
    f"transcription fails, update Windows (Settings › Windows Update), restart, and {REPORT}."
)


class OnnxRuntimeMismatch(Exception):
    """sherpa-onnx got another ONNX Runtime, one that can't serve it."""

    def __init__(self, detail: str, from_source: bool):
        super().__init__(FAILED + (FROM_SOURCE if from_source else ""))
        self.detail = detail


def same_file(a: Path | str, b: Path | str) -> bool:
    """Windows paths compare without regard to case or the form of the path."""
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def api_version(dll: Path) -> int:
    """The ONNX Runtime API version a DLL provides: its file version's minor number."""
    data = dll.read_bytes()
    i = data.find(struct.pack("<I", 0xFEEF04BD))  # VS_FIXEDFILEINFO
    if i < 0:
        raise ValueError(f"{dll} has no version information")
    (ms,) = struct.unpack_from("<I", data, i + 8)
    return ms & 0xFFFF


def loaded_module(name: str) -> Path | None:
    """Where the already loaded DLL `name` came from, or None if it isn't loaded."""
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    kernel32.GetModuleFileNameW.restype = wintypes.DWORD
    handle = kernel32.GetModuleHandleW(name)
    if not handle:
        return None
    buf = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetModuleFileNameW(handle, buf, len(buf))
    return Path(buf.value) if length else None


class _OrtApiBase(ctypes.Structure):
    _fields_ = [
        ("GetApi", ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_uint32)),
        ("GetVersionString", ctypes.CFUNCTYPE(ctypes.c_char_p)),
    ]


def serves(dll: Path, api: int) -> tuple[bool, str]:
    """Whether an ONNX Runtime DLL can serve API version `api`, and its version string.
    Asks the DLL itself, as sherpa-onnx does (an unsupported version also logs a line)."""
    lib = ctypes.WinDLL(str(dll))  # already loaded: the same module
    lib.OrtGetApiBase.restype = ctypes.POINTER(_OrtApiBase)
    base = lib.OrtGetApiBase().contents
    return bool(base.GetApi(api)), (base.GetVersionString() or b"?").decode()


@dataclass(frozen=True)
class Notice:
    """A warning: `text` for the job's log, `detail` (versions, paths) for worker.log."""

    text: str
    detail: str


def assess(
    loaded: Path, ours: Path, ok: bool, version: str, api: int, from_source: bool
) -> Notice | None:
    """A warning if another copy is in use but can serve sherpa-onnx, None if ours is in
    use; raises OnnxRuntimeMismatch if the other copy can't serve it."""
    if same_file(loaded, ours):
        return None
    detail = f"ONNX Runtime {version} was loaded from {loaded} instead of {ours}"
    if not ok:
        raise OnnxRuntimeMismatch(f"{detail}; it can't serve API version {api}.", from_source)
    return Notice(
        WARNING + (FROM_SOURCE if from_source else ""),
        f"{detail}; it serves API version {api}, so the job goes on.",
    )


def check() -> Notice | None:
    """Load sherpa-onnx and check its ONNX Runtime (Windows only; see the module docstring)."""
    if sys.platform != "win32":
        return None
    import sherpa_onnx

    folder = Path(sherpa_onnx.__file__).resolve().parent / "lib"
    renamed = (folder / BUNDLED).exists()  # only the Windows bundle renames it
    ours = folder / (BUNDLED if renamed else PLAIN)
    loaded = loaded_module(ours.name)
    if loaded is None or same_file(loaded, ours):
        return None
    api = api_version(ours)
    ok, version = serves(loaded, api)
    return assess(loaded, ours, ok, version, api, from_source=not renamed)
