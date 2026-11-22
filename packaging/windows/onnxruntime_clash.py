# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Run sherpa-onnx's voice detector with another onnxruntime.dll already loaded.

    python onnxruntime_clash.py <silero_vad.onnx> <an older onnxruntime.dll>

Windows 11 has its own, older onnxruntime.dll; WaveMaterial 1.0.0 crashed when sherpa-onnx
got that copy instead of the bundled one. Run by build.py in the installed app. Also checks
that WaveMaterial's own ONNX Runtime check (engine/onnxruntime_check.py) passes for the
bundle and can tell a foreign onnxruntime.dll apart.
"""

import ctypes
import sys

ctypes.WinDLL(sys.argv[2])

import numpy as np  # noqa: E402 (the DLL must be loaded first)
import sherpa_onnx  # noqa: E402

config = sherpa_onnx.VadModelConfig()
config.silero_vad.model = sys.argv[1]
config.sample_rate = 16000
vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
vad.accept_waveform(np.zeros(16000, dtype=np.float32))
vad.flush()

# WaveMaterial's own check (engine/onnxruntime_check.py), with real DLLs: the bundle passes
# (sherpa-onnx uses its renamed copy); the old onnxruntime.dll is seen as unable to serve
# sherpa-onnx (a job would fail plainly), and our own copy as able to (a job would only warn).
from pathlib import Path  # noqa: E402

from wavematerial.engine import onnxruntime_check as oc  # noqa: E402

if oc.check() is not None:
    sys.exit("The bundle's own ONNX Runtime check complained.")
ours = Path(sherpa_onnx.__file__).resolve().parent / "lib" / oc.BUNDLED
api = oc.api_version(ours)
old = oc.loaded_module(oc.PLAIN)
if old is None or not oc.same_file(old, sys.argv[2]):
    sys.exit(f"Expected the old onnxruntime.dll to be loaded, found {old}.")
old_ok, old_version = oc.serves(old, api)
ours_ok, ours_version = oc.serves(ours, api)
if old_ok or not ours_ok:
    sys.exit(f"API {api}: {old_version} serves it: {old_ok}; {ours_version}: {ours_ok}.")
try:
    oc.assess(old, ours, old_ok, old_version, api, from_source=False)
    sys.exit("The check did not fail for an ONNX Runtime that can't serve sherpa-onnx.")
except oc.OnnxRuntimeMismatch:
    pass
print(
    f"sherpa-onnx ran with another onnxruntime.dll loaded; the check agrees "
    f"(API {api}: {old_version} can't serve it, {ours_version} can)"
)
