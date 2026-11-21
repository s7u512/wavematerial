# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The engine's pure steps: token grouping, chunk padding, alignment, and speaker merge.

Sample text is from NASA's Apollo 11 air-to-ground transcript (public domain).
"""

from wavematerial.engine.align import AlignStats, align_chunk, drop_cjk
from wavematerial.engine.merge import SpeakerSegment, merge
from wavematerial.engine.timings import tokens_to_words
from wavematerial.engine.vad import pad_chunks
from wavematerial.transcript.schema import Word


def test_tokens_group_into_words_with_offsets():
    tokens = [" Tr", "anqu", "ility", " Base", ",", " ", "1", "9", "6", "9"]
    starts = [0.0, 0.1, 0.2, 0.5, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
    words = tokens_to_words(tokens, starts, [0.1] * len(tokens), offset=10.0)
    assert [(w.text, w.start, w.end) for w in words] == [
        ("Tranquility", 10.0, 10.3),
        ("Base,", 10.5, 10.9),
        ("1969", 11.0, 11.4),  # the bare space token starts a new word before digits
    ]


def test_padding_reaches_into_silence_but_never_overlaps():
    chunks = [(1.0, 5.0), (5.2, 9.0), (12.0, 15.0)]
    assert pad_chunks(chunks, duration=15.1, pad=0.2) == [
        (0.8, 5.1),  # only halfway into the 0.2 s gap
        (5.1, 9.2),
        (11.8, 15.1),  # not past the end of the audio
    ]


def test_aligner_takes_exact_timings_and_spreads_the_rest():
    parakeet = [
        Word("The", 1.0, 1.2),
        Word("eagle", 1.2, 1.6),
        Word("has", 1.7, 1.9),
        Word("lended", 1.9, 2.5),
    ]
    stats = AlignStats()
    words = align_chunk("The Eagle has landed.", parakeet, (0.8, 3.0), stats)
    assert [(w.text, w.start, w.end) for w in words] == [
        ("The", 1.0, 1.2),
        ("Eagle", 1.2, 1.6),  # same word, different case: exact
        ("has", 1.7, 1.9),
        ("landed.", 1.9, 2.5),  # differs: takes the span of the word it replaces
    ]
    assert (stats.exact, stats.interpolated) == (3, 1)


def test_aligner_inserts_words_into_the_gap_and_falls_back_when_qwen_is_silent():
    parakeet = [Word("Houston", 2.0, 2.5), Word("here", 3.5, 4.0)]
    words = align_chunk("Houston, Tranquility Base here.", parakeet, (1.0, 5.0))
    assert [w.text for w in words] == ["Houston,", "Tranquility", "Base", "here."]
    gap = words[1:3]
    assert words[0].end <= gap[0].start < gap[1].end <= words[3].start  # inside the gap

    stats = AlignStats()
    assert align_chunk("", parakeet, (1.0, 5.0), stats) == parakeet
    assert stats.fallback_chunks == 1


def test_merge_assigns_by_overlap_and_names_speakers_in_order():
    words = [
        Word("Contact", 0.0, 0.5),
        Word("light.", 0.5, 1.0),
        Word("Shutdown.", 1.2, 1.6),  # in a gap: stays with the current speaker
        Word("Roger,", 3.0, 3.5),
        Word("Eagle.", 3.5, 4.0),
    ]
    segments = [SpeakerSegment(0.0, 1.1, 7), SpeakerSegment(2.9, 4.2, 3)]
    speakers, turns = merge(words, segments)
    assert speakers == ("SPEAKER_00", "SPEAKER_01")
    assert [(t.speaker, t.text) for t in turns] == [
        ("SPEAKER_00", "Contact light. Shutdown."),
        ("SPEAKER_01", "Roger, Eagle."),
    ]


def test_cjk_fillers_are_dropped_without_gluing_words_together():
    assert drop_cjk("嗯 white spectre commission") == "white spectre commission"
    assert drop_cjk("Roger，嗯，copy that.") == "Roger copy that."
    assert drop_cjk("the Voelcker report嗯.") == "the Voelcker report ."
    assert drop_cjk("Tranquility Base, 1969: café naïve") == "Tranquility Base, 1969: café naïve"
