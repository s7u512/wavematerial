# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
from wavematerial.config import Settings, load_settings, save_settings


def test_bad_values_fall_back_without_losing_good_ones(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'device = "vulkan:0000:05:00.0"\n'
        "threads = -4\n"
        'max_speakers = "three"\n'
        'key_terms = ["Tranquility", "  ", " CAPCOM "]\n'
        "update_check = 1\n"
        'colour = "red"\n',
        encoding="utf-8",
    )
    s = load_settings(path)
    assert s.device == "vulkan:0000:05:00.0"
    assert s.threads == Settings.threads
    assert s.max_speakers == Settings.max_speakers
    assert s.key_terms == ["Tranquility", "CAPCOM"]
    assert s.update_check is True


def test_speaker_range_upside_down_resets_both(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("min_speakers = 5\nmax_speakers = 2\n", encoding="utf-8")
    s = load_settings(path)
    assert (s.min_speakers, s.max_speakers) == (Settings.min_speakers, Settings.max_speakers)


def test_unreadable_file_gives_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("device = [unterminated", encoding="utf-8")
    assert load_settings(path) == Settings()


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    s = Settings(device="cpu", threads=4, key_terms=["Eagle"], models_dir="/mnt/models")
    save_settings(path, s)
    assert load_settings(path) == s
