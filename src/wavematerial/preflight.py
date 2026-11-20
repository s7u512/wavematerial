# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Startup preflight: choose the compute device by detection only (no benchmarking).

Order: a real Vulkan GPU, then the CPU with physical cores - 1 threads. Software
rasterisers count as no GPU, and under WSL the translated Dozen device is not preferred.
The whole preflight must stay under 2 seconds.
"""

from __future__ import annotations

import logging
import platform
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from pathlib import Path

import psutil

from wavematerial.config import Settings

log = logging.getLogger(__name__)

_SOFTWARE_RENDERERS = ("llvmpipe", "lavapipe", "swiftshader")
_WSL_TRANSLATED = ("dozen", "dzn", "microsoft direct3d12")


@dataclass(frozen=True)
class Device:
    """A compute device as transcribe.cpp reports it."""

    kind: str  # "vulkan", "cpu", ...
    device_type: str  # "gpu", "igpu", "cpu", ...
    description: str
    device_id: str | None  # stable hardware id (PCI bus id) for GPUs
    memory_total: int = 0


@dataclass(frozen=True)
class Choice:
    """What a job will run on, and why, in words the UI can show."""

    backend: str  # "vulkan" or "cpu"
    device_id: str | None
    description: str
    threads: int
    reason: str


def physical_cores() -> int:
    return psutil.cpu_count(logical=False) or psutil.cpu_count() or 1


def in_wsl() -> bool:
    if platform.system() != "Linux":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _is_software(d: Device) -> bool:
    return any(s in d.description.lower() for s in _SOFTWARE_RENDERERS)


def _is_wsl_translated(d: Device) -> bool:
    return any(s in d.description.lower() for s in _WSL_TRANSLATED)


def usable_gpus(devices: Iterable[Device], wsl: bool) -> list[Device]:
    """Real Vulkan GPUs, best first (discrete before integrated, then by memory)."""
    gpus = [
        d
        for d in devices
        if d.kind == "vulkan" and not _is_software(d) and not (wsl and _is_wsl_translated(d))
    ]
    return sorted(gpus, key=lambda d: (d.device_type != "gpu", -d.memory_total))


def choose(
    devices: Iterable[Device],
    settings: Settings,
    *,
    cores: int,
    wsl: bool = False,
    unreliable: Collection[str] = (),
) -> Choice:
    """Pick the device for a job. Pure: everything it depends on is passed in."""
    devices = list(devices)
    threads = settings.threads or max(1, cores - 1)
    cpu = next((d for d in devices if d.kind == "cpu"), None)
    cpu_name = cpu.description if cpu else "CPU"

    def on_cpu(reason: str) -> Choice:
        return Choice("cpu", None, cpu_name, threads, reason)

    if settings.device == "cpu":
        return on_cpu("Using the CPU, as set in Settings.")

    gpus = usable_gpus(devices, wsl)
    if settings.device.startswith("vulkan:"):
        wanted = settings.device.removeprefix("vulkan:")
        match = next((d for d in gpus if d.device_id == wanted), None)
        if match:
            return Choice("vulkan", match.device_id, match.description, threads, "Set in Settings.")
        log.warning("The GPU chosen in Settings (%s) was not found; choosing automatically", wanted)

    reliable = [d for d in gpus if d.device_id not in unreliable]
    if reliable:
        d = reliable[0]
        return Choice("vulkan", d.device_id, d.description, threads, "Fast mode: using the GPU.")
    if gpus:
        return on_cpu("Using the CPU: the GPU failed before on this computer.")
    if wsl and any(d.kind == "vulkan" and _is_wsl_translated(d) for d in devices):
        return on_cpu("Using the CPU: under WSL the GPU is only reachable through a slow layer.")
    return on_cpu("Using the CPU: no GPU with Vulkan support was found.")


def detect_devices() -> list[Device]:
    """Ask transcribe.cpp which devices this process can run on (well under a second)."""
    import transcribe_cpp

    return [
        Device(d.kind, d.device_type, d.description, d.device_id, d.memory_total)
        for d in transcribe_cpp.backends()
    ]
