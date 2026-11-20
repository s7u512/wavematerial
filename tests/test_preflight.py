# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
from wavematerial.config import Settings
from wavematerial.preflight import Device, choose

CPU = Device("cpu", "cpu", "Test CPU", None)
IGPU = Device("vulkan", "igpu", "AMD Radeon 660M (RADV REMBRANDT)", "0000:05:00.0", 8 << 30)
DGPU = Device("vulkan", "gpu", "NVIDIA GeForce RTX 3060", "0000:01:00.0", 12 << 30)
LLVMPIPE = Device("vulkan", "cpu", "llvmpipe (LLVM 19.1.7, 256 bits)", None)
DOZEN = Device("vulkan", "gpu", "Microsoft Direct3D12 (dzn)", "dzn-0", 8 << 30)


def test_prefers_a_discrete_gpu_and_ignores_software_renderers():
    c = choose([CPU, LLVMPIPE, IGPU, DGPU], Settings(), cores=6)
    assert (c.backend, c.device_id, c.threads) == ("vulkan", DGPU.device_id, 5)

    c = choose([CPU, LLVMPIPE], Settings(), cores=6)
    assert c.backend == "cpu" and "no GPU" in c.reason


def test_wsl_translated_gpu_is_not_used():
    c = choose([CPU, DOZEN], Settings(), cores=4, wsl=True)
    assert c.backend == "cpu" and "WSL" in c.reason


def test_gpu_that_failed_before_falls_back_to_cpu():
    c = choose([CPU, IGPU], Settings(), cores=6, unreliable={IGPU.device_id})
    assert c.backend == "cpu" and "failed before" in c.reason


def test_settings_override_and_missing_device():
    assert choose([CPU, IGPU], Settings(device="cpu", threads=3), cores=6).threads == 3
    c = choose([CPU, IGPU, DGPU], Settings(device=f"vulkan:{IGPU.device_id}"), cores=6)
    assert c.device_id == IGPU.device_id
    c = choose([CPU, DGPU], Settings(device="vulkan:0000:09:00.0"), cores=6)
    assert c.device_id == DGPU.device_id  # the chosen GPU is gone: choose automatically
