# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Model downloads against a local HTTP server (no network, no real models)."""

import dataclasses
import hashlib
import http.server
import io
import tarfile
import threading

import pytest

from wavematerial.models.download import DownloadError, install, is_installed, verify
from wavematerial.models.manifest import FileSpec, ModelSpec

PAYLOAD = bytes(range(256)) * 4096  # 1 MiB


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Server:
    """Serves `files`; honours Range; can cut the first response short."""

    def __init__(self, files: dict[str, bytes], drop_first_after: int | None = None):
        self.files = files
        self.drop_first_after = drop_first_after
        self.requests: list[str | None] = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                data = server.files[self.path]
                rng = self.headers.get("Range")
                server.requests.append(rng)
                start = int(rng.removeprefix("bytes=").rstrip("-")) if rng else 0
                body = data[start:]
                self.send_response(206 if rng else 200)
                if rng:
                    self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if server.drop_first_after is not None and len(server.requests) == 1:
                    body = body[: server.drop_first_after]  # then close: a dropped connection
                    self.close_connection = True
                self.wfile.write(body)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def server_factory():
    servers = []

    def make(*args, **kwargs):
        s = _Server(*args, **kwargs)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


def _spec(url: str, data: bytes, files: tuple[FileSpec, ...], **kw) -> ModelSpec:
    return ModelSpec(
        id="test-model",
        name="Test model",
        role="test",
        licence="MIT",
        creator="test",
        model_card="https://example.invalid",
        changes="",
        url=url,
        size=len(data),
        sha256=_sha(data),
        files=files,
        **kw,
    )


def test_interrupted_download_resumes_and_installs(tmp_path, server_factory):
    srv = server_factory({"/m.bin": PAYLOAD}, drop_first_after=300_000)
    spec = _spec(srv.url + "/m.bin", PAYLOAD, (FileSpec("m.bin", len(PAYLOAD), _sha(PAYLOAD)),))
    models, cache = tmp_path / "models", tmp_path / "cache"

    install(spec, models, cache, backoff=0)

    assert srv.requests == [None, "bytes=300000-"]
    assert (models / "test-model" / "m.bin").read_bytes() == PAYLOAD
    assert is_installed(spec, models) and verify(spec, models) == []
    assert list(cache.iterdir()) == []


def test_wrong_checksum_installs_nothing(tmp_path, server_factory):
    srv = server_factory({"/m.bin": PAYLOAD})
    good = (FileSpec("m.bin", len(PAYLOAD), _sha(PAYLOAD)),)
    spec = _spec(srv.url + "/m.bin", PAYLOAD, good)
    spec = dataclasses.replace(spec, sha256="0" * 64)
    models, cache = tmp_path / "models", tmp_path / "cache"

    with pytest.raises(DownloadError, match="checksum"):
        install(spec, models, cache, backoff=0)

    assert not is_installed(spec, models)
    assert list(cache.iterdir()) == [] and list(models.iterdir()) == []


def _tar_bz2(members: dict[str, bytes], symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        if symlink:
            info = tarfile.TarInfo(symlink)
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
    return buf.getvalue()


def test_archive_installs_only_the_listed_files(tmp_path, server_factory):
    enc, tok = b"encoder" * 1000, b"tokens"
    archive = _tar_bz2({"root/enc.onnx": enc, "root/tokens.txt": tok, "root/test.wav": b"x"})
    srv = server_factory({"/a.tar.bz2": archive})
    files = (FileSpec("enc.onnx", len(enc), _sha(enc)), FileSpec("tokens.txt", len(tok), _sha(tok)))
    spec = _spec(srv.url + "/a.tar.bz2", archive, files, archive="tar.bz2", archive_root="root")
    models = tmp_path / "models"

    install(spec, models, tmp_path / "cache", backoff=0)

    assert sorted(p.name for p in (models / "test-model").iterdir()) == ["enc.onnx", "tokens.txt"]
    assert verify(spec, models) == []


def test_archive_member_that_is_not_a_file_is_refused(tmp_path, server_factory):
    archive = _tar_bz2({}, symlink="root/enc.onnx")
    srv = server_factory({"/a.tar.bz2": archive})
    files = (FileSpec("enc.onnx", 10, "0" * 64),)
    spec = _spec(srv.url + "/a.tar.bz2", archive, files, archive="tar.bz2", archive_root="root")
    models = tmp_path / "models"

    with pytest.raises(DownloadError, match="not a file"):
        install(spec, models, tmp_path / "cache", backoff=0)

    assert list(models.iterdir()) == []
