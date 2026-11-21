# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Run sherpa-onnx's voice detector with another onnxruntime.dll already loaded.

    python onnxruntime_clash.py <silero_vad.onnx> <an older onnxruntime.dll>

Windows 11 has its own, older onnxruntime.dll; WaveMaterial 1.0.0 crashed when sherpa-onnx
got that copy instead of the bundled one. Run by build.py in the installed app.
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
print("sherpa-onnx ran with another onnxruntime.dll loaded")
