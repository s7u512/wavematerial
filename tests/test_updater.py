# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Self-update and Manual update, against a local stand-in for the release page."""

import hashlib
import io
import json
import tarfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from wavematerial import updater as up
from wavematerial.updates import TEST_SERVER, UpdateChecker

NEW = "9.9.9"
ASSET = f"wavematerial-{NEW}-linux-x86_64.tar.gz"


def _bundle(path, version):
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "wavematerial").write_text(version, encoding="utf-8")
    (path / "BUILD-INFO.txt").write_text(f"WaveMaterial {version}\n", encoding="utf-8")


def _tarball(top: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in ((f"{top}/bin/wavematerial", NEW), (f"{top}/BUILD-INFO.txt", NEW)):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data.encode()))
    return buf.getvalue()


@pytest.fixture
def release(tmp_path, monkeypatch):
    """A local release page serving NEW; returns (install, server folder, base url)."""
    site = tmp_path / "site"
    (site / "releases").mkdir(parents=True)
    (site / "download").mkdir()
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(site))
    )
    server.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv(TEST_SERVER, base)

    def publish(data: bytes, sums_digest: str | None = None):
        (site / "download" / ASSET).write_bytes(data)
        digest = sums_digest or hashlib.sha256(data).hexdigest()
        (site / "download" / "SHA256SUMS").write_text(f"{digest}  {ASSET}\n", encoding="utf-8")
        assets = [
            {"name": n, "size": (site / "download" / n).stat().st_size,
             "browser_download_url": f"{base}/download/{n}"}
            for n in (ASSET, "SHA256SUMS")
        ]  # fmt: skip
        latest = {"tag_name": f"v{NEW}", "html_url": base, "assets": assets}
        (site / "releases" / "latest").write_text(json.dumps(latest), encoding="utf-8")

    root = tmp_path / "apps" / "wavematerial-1.2.0-linux-x86_64"
    _bundle(root, "1.2.0")
    yield up.Install("tarball", root), publish, tmp_path
    server.shutdown()


def _download(install, tmp_path, mode="self"):
    checker = UpdateChecker(tmp_path / "update.json")
    checker._check()
    assert checker.update_available()
    u = up.Updater(tmp_path / "cache", install, downloads=lambda: tmp_path / "Downloads")
    ready = threading.Event()
    u.start(checker.status.latest, checker.status.assets, mode, ready.set)
    deadline = time.monotonic() + 20
    while u.state == "downloading" and time.monotonic() < deadline:
        time.sleep(0.05)
    return u, ready.is_set()


def test_the_tarball_updates_itself_and_keeps_the_previous_folder(release, monkeypatch):
    install, publish, tmp_path = release
    publish(_tarball(ASSET.removesuffix(".tar.gz")))
    started = []
    monkeypatch.setattr(up.subprocess, "Popen", lambda args, **kw: started.append(args))

    u, ready = _download(install, tmp_path)
    assert ready and u.state == "waiting", u.error
    u.mark_ready()
    u.apply()

    root = install.root
    assert (root / "bin" / "wavematerial").read_text(encoding="utf-8") == NEW
    previous = root.with_name(root.name + ".previous")
    assert (previous / "bin" / "wavematerial").read_text(encoding="utf-8") == "1.2.0"
    assert sorted(p.name for p in root.parent.iterdir()) == [root.name, previous.name]
    assert started == [[str(root / "bin" / "wavematerial")]]  # and it restarts


def test_a_download_that_doesnt_match_the_checksum_is_refused(release):
    install, publish, tmp_path = release
    publish(_tarball(ASSET.removesuffix(".tar.gz")), sums_digest="0" * 64)

    u, ready = _download(install, tmp_path)
    assert not ready and u.state == "error" and "checksum" in u.error
    u.mark_ready()
    u.apply()  # nothing to install
    assert (install.root / "bin" / "wavematerial").read_text(encoding="utf-8") == "1.2.0"


def test_a_tarball_with_files_outside_its_folder_is_refused(release):
    install, publish, tmp_path = release
    publish(_tarball("somewhere-else"))

    u, ready = _download(install, tmp_path)
    assert not ready and u.state == "error" and "unexpected layout" in u.error


def test_files_from_anywhere_but_the_release_page_are_refused(tmp_path):
    u = up.Updater(tmp_path / "cache", up.Install("tarball", tmp_path / "app"))
    assets = {
        ASSET: {"url": "https://example.com/" + ASSET, "size": 1},
        "SHA256SUMS": {"url": "https://example.com/SHA256SUMS", "size": 1},
    }
    done = threading.Event()
    u.start(NEW, assets, "self", done.set)
    u._thread.join(10)
    assert u.state == "error" and "release page" in u.error and not done.is_set()


def test_tarball_manual_update_only_saves_a_checked_copy(release, monkeypatch):
    install, publish, tmp_path = release
    data = _tarball(ASSET.removesuffix(".tar.gz"))
    publish(data)
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / ASSET).write_bytes(b"an older download")  # never overwritten
    started = []
    monkeypatch.setattr(up.subprocess, "Popen", lambda args, **kw: started.append(args))

    u, ready = _download(install, tmp_path, mode="manual")
    assert u.state == "saved" and not ready, u.error  # the app keeps running
    assert u.saved == tmp_path / "Downloads" / ASSET.replace(".tar.gz", " (2).tar.gz")
    assert u.saved.read_bytes() == data
    assert (tmp_path / "Downloads" / ASSET).read_bytes() == b"an older download"
    u.mark_ready()
    u.apply()
    assert started == [] and (install.root / "bin" / "wavematerial").read_text() == "1.2.0"


@pytest.mark.parametrize(
    ("mode", "args"),
    [
        ("self", ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/UPDATE=1"]),
        ("manual", ["/WAIT=1"]),
    ],
)
def test_windows_modes_start_the_installer_the_right_way(tmp_path, monkeypatch, mode, args):
    monkeypatch.setattr(up.subprocess, "DETACHED_PROCESS", 8, raising=False)
    monkeypatch.setattr(up.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    started = []
    monkeypatch.setattr(up.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    u = up.Updater(tmp_path / "cache", up.Install("windows", tmp_path / "app"))
    assert u.closes_app("self") and u.closes_app("manual")
    setup = tmp_path / "setup.exe"
    u._file, u.state, u.mode = setup, "ready", mode
    u.apply()
    assert started == [[str(setup), *args]]
