# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
import dataclasses
import json

import pytest

from wavematerial.transcript.schema import Turn, Word
from wavematerial.transcript.store import (
    ARTIFACT,
    REVISION,
    read_artifact,
    read_current,
    restore_original,
    save_revision,
    write_artifact,
)


def _edit(transcript):
    """Fix a word and name a speaker, as the editor would."""
    first = transcript.turns[0]
    fixed = Turn(first.speaker, (Word("Thirty", 0.5, 0.9), *first.words[1:]))
    return dataclasses.replace(
        transcript,
        turns=(fixed, *transcript.turns[1:]),
        speaker_names={"SPEAKER_00": "Duke"},
    )


def test_artifact_round_trips_and_cannot_be_overwritten(tmp_path, apollo):
    write_artifact(tmp_path, apollo)
    assert read_artifact(tmp_path) == apollo
    with pytest.raises(FileExistsError):
        write_artifact(tmp_path, apollo)


def test_saving_edits_never_touches_the_artifact(tmp_path, apollo):
    write_artifact(tmp_path, apollo)
    before = (tmp_path / ARTIFACT).read_bytes()

    save_revision(tmp_path, _edit(apollo))
    save_revision(tmp_path, _edit(apollo))

    assert (tmp_path / ARTIFACT).read_bytes() == before
    current = read_current(tmp_path)
    assert current.turns[0].text == "Thirty seconds."
    assert current.display_name("SPEAKER_00") == "Duke"

    restore_original(tmp_path)
    assert read_current(tmp_path) == apollo


def test_revision_for_another_artifact_is_ignored(tmp_path, apollo):
    other = tmp_path / "other"
    other.mkdir()
    write_artifact(other, dataclasses.replace(apollo, language="fr"))
    save_revision(other, _edit(apollo))

    write_artifact(tmp_path, apollo)
    (tmp_path / REVISION).write_bytes((other / REVISION).read_bytes())

    assert read_current(tmp_path) == apollo


def test_corrupt_revision_falls_back_to_the_original(tmp_path, apollo):
    write_artifact(tmp_path, apollo)
    (tmp_path / REVISION).write_text("{not json", encoding="utf-8")
    assert read_current(tmp_path) == apollo


def test_reads_the_bench_artifact_layout(tmp_path):
    """Schema version 1 is the layout the engine bench wrote; stored text is ignored."""
    data = {
        "schema_version": 1,
        "language": "en",
        "duration_seconds": 3.0,
        "speakers": ["SPEAKER_00"],
        "engine": {"device": "vulkan"},
        "turns": [
            {
                "speaker": "SPEAKER_00",
                "start": 0.0,
                "end": 2.0,
                "text": "stale text",
                "words": [
                    {"word": "Eagle", "start": 0.0, "end": 0.8},
                    {"word": "landed.", "start": 1.0, "end": 2.0},
                ],
            },
            {"speaker": "SPEAKER_00", "start": 2.0, "end": 2.0, "text": "", "words": []},
        ],
    }
    (tmp_path / ARTIFACT).write_text(json.dumps(data), encoding="utf-8")
    t = read_artifact(tmp_path)
    assert [turn.text for turn in t.turns] == ["Eagle landed."]


def test_replace_waits_out_a_brief_lock_on_windows_only(tmp_path, monkeypatch):
    import os

    from wavematerial import _fsutil

    src, dst = tmp_path / "new", tmp_path / "old"
    calls = []
    real = os.replace

    def flaky(a, b):
        calls.append(1)
        if len(calls) < 3:  # e.g. an antivirus scan holds the target for a moment
            raise PermissionError(13, "in use")
        real(a, b)

    monkeypatch.setattr(_fsutil.os, "replace", flaky)
    monkeypatch.setattr(_fsutil.time, "sleep", lambda s: None)
    src.write_text("x", encoding="utf-8")
    monkeypatch.setattr(_fsutil.sys, "platform", "linux")
    with pytest.raises(PermissionError):
        _fsutil.replace(src, dst)  # elsewhere it's a real error: no retry
    calls.clear()
    monkeypatch.setattr(_fsutil.sys, "platform", "win32")
    _fsutil.replace(src, dst)
    assert len(calls) == 3 and dst.read_text(encoding="utf-8") == "x"
