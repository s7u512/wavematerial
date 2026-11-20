# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Stage 5: who spoke when. pyannote segmentation 3.0 + TitaNet small + fast clustering."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from wavematerial.engine.merge import SpeakerSegment

WINDOW_SHIFT_RATIO = 0.5
THRESHOLD = 1.0  # 0.5 over-splits speakers on the test recording


def diarize(
    audio: np.ndarray,
    segmentation_model: Path,
    embedding_model: Path,
    min_speakers: int,
    max_speakers: int,
    threads: int,
) -> list[SpeakerSegment]:
    """Speaker segments, sorted by start time.

    Clustering by threshold decides the number of speakers; if that falls outside
    [min_speakers, max_speakers], it is redone with the nearest allowed number.
    """
    import sherpa_onnx as so

    pyannote = so.OfflineSpeakerSegmentationPyannoteModelConfig()
    pyannote.model = str(segmentation_model)
    pyannote.window_shift_ratio = WINDOW_SHIFT_RATIO
    segmentation = so.OfflineSpeakerSegmentationModelConfig()
    segmentation.pyannote = pyannote
    segmentation.num_threads = threads
    embedding = so.SpeakerEmbeddingExtractorConfig()
    embedding.model = str(embedding_model)
    embedding.num_threads = threads
    config = so.OfflineSpeakerDiarizationConfig(
        segmentation=segmentation,
        embedding=embedding,
        clustering=so.FastClusteringConfig(num_clusters=-1, threshold=THRESHOLD),
    )
    sd = so.OfflineSpeakerDiarization(config)
    result = sd.process(audio).sort_by_start_time()
    found = len({s.speaker for s in result})
    if found and not min_speakers <= found <= max_speakers:
        config.clustering = so.FastClusteringConfig(
            num_clusters=min(max(found, min_speakers), max_speakers)
        )
        sd.set_config(config)
        result = sd.process(audio).sort_by_start_time()
    return [SpeakerSegment(round(s.start, 3), round(s.end, 3), int(s.speaker)) for s in result]
