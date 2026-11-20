# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
import dataclasses
import json

from wavematerial.transcript.render import (
    format_timestamp,
    render_json,
    render_srt,
    render_txt,
    render_vtt,
)
from wavematerial.transcript.schema import Turn, Word


def test_timestamps_carry_when_rounding_up():
    assert format_timestamp(59.9996, ",") == "00:01:00,000"
    assert format_timestamp(3725.25, ".") == "01:02:05.250"
    assert format_timestamp(-0.001, ".") == "00:00:00.000"


def test_outputs_use_speaker_names(apollo):
    named = dataclasses.replace(apollo, speaker_names={"SPEAKER_01": "Aldrin"})

    assert render_txt(named) == (
        "SPEAKER_00: 30 seconds.\n\n"
        "Aldrin: Contact light.\n\n"
        "Aldrin: Houston, Tranquility Base here.\n\n"
    )
    assert render_srt(named) == (
        "1\n00:00:00,500 --> 00:00:01,500\nSPEAKER_00: 30 seconds.\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nAldrin: Contact light.\n\n"
        "3\n00:00:05,250 --> 00:00:07,250\nAldrin: Houston, Tranquility Base here.\n"
    )
    assert render_vtt(named) == (
        "WEBVTT\n\n"
        "00:00:00.500 --> 00:00:01.500\nSPEAKER_00: 30 seconds.\n\n"
        "00:00:02.000 --> 00:00:03.000\nAldrin: Contact light.\n\n"
        "00:00:05.250 --> 00:00:07.250\nAldrin: Houston, Tranquility Base here.\n"
    )
    data = json.loads(render_json(named))
    assert data["speakers"] == [
        {"id": "SPEAKER_00", "name": "SPEAKER_00"},
        {"id": "SPEAKER_01", "name": "Aldrin"},
    ]
    assert [t["speaker_name"] for t in data["turns"]] == ["SPEAKER_00", "Aldrin", "Aldrin"]


def test_vtt_escapes_markup_in_text(apollo):
    turn = Turn("SPEAKER_00", (Word("<b>R&D</b>", 0.0, 1.0),))
    vtt = render_vtt(dataclasses.replace(apollo, turns=(turn,)))
    assert "SPEAKER_00: &lt;b&gt;R&amp;D&lt;/b&gt;\n" in vtt
