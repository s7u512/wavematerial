# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Where the models go: the folder rules, the space a download needs, and removing them."""

import os

import pytest

from wavematerial.models import folders
from wavematerial.models.manifest import load_manifest

MANIFEST = load_manifest()


def test_a_fresh_download_needs_3_7_gb():
    # 2.72 GB to download + 0.67 GB Parakeet unpacked, + 10%, to the nearest 100 MB
    assert folders.space_needed(MANIFEST, {}) == 3_700_000_000
    qwen = next(m for m in MANIFEST if m.id.startswith("qwen"))
    half = folders.space_needed([qwen], {qwen.id: qwen.size // 2})
    assert half == round(qwen.size // 2 * 1.1 / 1e8) * 100_000_000  # only what is left


def test_a_chosen_folder_gets_a_models_subfolder_unless_it_is_one(tmp_path):
    assert folders.models_folder_for(tmp_path, MANIFEST) == tmp_path / "WaveMaterial models"
    named = tmp_path / "WaveMaterial models"
    assert folders.models_folder_for(named, MANIFEST) == named
    holding = tmp_path / "my models"  # already holds our models: used as it is
    MANIFEST[0].folder(holding).mkdir(parents=True)
    assert folders.models_folder_for(holding, MANIFEST) == holding


def test_onedrive_folders_are_refused(tmp_path):
    env = {"OneDrive": str(tmp_path / "OneDrive")}
    assert folders.in_onedrive(tmp_path / "OneDrive" / "Documents" / "x", env)
    assert not folders.in_onedrive(tmp_path / "OneDriveNot" / "x", env)
    assert not folders.in_onedrive(tmp_path / "x", {})


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs a non-root POSIX user")
def test_a_folder_that_cant_be_written_is_refused_and_left_clean(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    try:
        assert folders.problem_with(locked / "WaveMaterial models") == folders.CANT_WRITE
        assert list(locked.iterdir()) == []
    finally:
        locked.chmod(0o700)
    assert folders.problem_with(tmp_path / "fine" / "WaveMaterial models") is None


def test_removing_deletes_only_the_models(tmp_path):
    folder = tmp_path / "WaveMaterial models"
    for m in MANIFEST:
        (m.folder(folder)).mkdir(parents=True)
        (m.folder(folder) / "x.bin").write_bytes(b"0" * 10)
    (folder / ".downloads").mkdir()
    (folder / ".downloads" / "a.part").write_bytes(b"0" * 5)
    assert folders.remove_models(folder, MANIFEST, tmp_path / "default") == 10 * len(MANIFEST) + 5
    assert not folder.exists()  # ours and empty: gone too

    other = tmp_path / "shared"
    MANIFEST[0].folder(other).mkdir(parents=True)
    (other / "notes.txt").write_text("mine", encoding="utf-8")
    folders.remove_models(other, MANIFEST, tmp_path / "default")
    assert sorted(p.name for p in other.iterdir()) == ["notes.txt"]  # never touched
