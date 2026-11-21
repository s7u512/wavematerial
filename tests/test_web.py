# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The local web app: its access checks and the add-recordings flow (no window, no models)."""

import time
import wave

import av
import pytest

from wavematerial.config import Paths, load_settings
from wavematerial.jobs.scheduler import Scheduler
from wavematerial.jobs.store import JobStore
from wavematerial.models.installer import Installer
from wavematerial.models.manifest import load_manifest
from wavematerial.preflight import Device
from wavematerial.updates import UpdateChecker
from wavematerial.web import COOKIE, create_app
from wavematerial.web.context import AppContext

CPU = Device("cpu", "cpu", "Test CPU", None)


@pytest.fixture
def web(tmp_path):
    paths = Paths.under(tmp_path / "app")
    store = JobStore(paths.jobs_db)

    def settings():
        return load_settings(paths.settings_file)

    manifest = load_manifest()
    ctx = AppContext(
        paths=paths,
        store=store,
        scheduler=Scheduler(store, paths, settings, [CPU], cores=4),
        installer=Installer(manifest, lambda: paths.models_dir(settings()), paths.cache_dir),
        updates=UpdateChecker(paths.state_dir / "update.json"),
        manifest=manifest,
        devices=[CPU],
        cores=4,
        wsl=False,
        token="secret-token",
        port=5555,
    )
    client = create_app(ctx).test_client()
    return ctx, client, tmp_path


def _get(client, url, **kw):
    return client.get(url, base_url="http://127.0.0.1:5555", **kw)


def _post(client, url, **kw):
    return client.post(url, base_url="http://127.0.0.1:5555", **kw)


def test_access_needs_the_launch_token_and_the_local_host(web):
    _, client, _ = web
    assert _get(client, "/settings").status_code == 403
    assert _get(client, "/settings?token=wrong").status_code == 403

    r = _get(client, "/settings?token=secret-token")
    assert r.status_code == 302 and r.headers["Location"] == "/settings"
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie

    assert _get(client, "/settings").status_code == 200  # the cookie now carries the token
    other_host = client.get("/settings", base_url="http://evil.example:5555")
    assert other_host.status_code == 400  # DNS rebinding


def test_licence_viewer_stays_inside_its_folder(web):
    _, client, _ = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    assert _get(client, "/credits/licence/static/fonts/inter/OFL.txt").status_code == 200
    assert _get(client, "/credits/licence/static/../../config.py").status_code == 404


def test_adding_a_folder_queues_its_media_and_saves_defaults(web):
    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    folder = tmp / "recordings"
    (folder / "sub").mkdir(parents=True)
    for name in ("apollo11.wav", "sub/gemini4.wav"):
        with wave.open(str(folder / name), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
            w.writeframes(b"\0" * 8000)
    (folder / "notes.txt").write_text("not audio")

    listed = _post(client, "/add/files", data={"how": "typed", "dropped": f'["{folder}"]'})
    assert listed.get_data(as_text=True).count('name="paths"') == 2  # the .txt is skipped

    r = _post(
        client,
        "/add",
        data={
            "paths": [str(folder)],
            "min_speakers": "3",
            "max_speakers": "2",  # upside down: swapped, not rejected
            "key_terms": ["Tranquility", " "],
            "save_defaults": "1",
        },
    )
    assert r.status_code == 200
    jobs = ctx.store.all()
    assert sorted(j.name for j in jobs) == ["apollo11.wav", "gemini4.wav"]
    assert {(j.min_speakers, j.max_speakers, j.key_terms) for j in jobs} == {
        (2, 3, ("Tranquility",))
    }
    assert all(j.state == "queued" and j.duration == pytest.approx(0.5) for j in jobs)
    s = ctx.settings()
    assert (s.min_speakers, s.max_speakers, s.key_terms) == (2, 3, ["Tranquility"])


def test_library_poll_keeps_the_counts_current(web):
    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    for name in ("apollo11.wav", "gemini4.wav"):
        (tmp / name).write_bytes(b"\0")
        ctx.store.add(tmp / name, min_speakers=1, max_speakers=2)
    ctx.store.set_state(ctx.store.all()[0].id, "done")

    # The poll swaps only the table; the counts outside it ride along out of band.
    table = _get(client, "/library/table?filter=all").get_data(as_text=True)
    assert table.count('hx-swap-oob="true"') == 3
    assert "2 recordings · 1 in progress" in table
    assert 'Done <span class="chip-count">1</span>' in table
    assert 'id="nav-library-count" class="nav-count" hx-swap-oob="true">2<' in table


def test_editor_audio_is_made_once_for_older_jobs_and_seekable(web):
    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    source = tmp / "apollo11.wav"
    with wave.open(str(source), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(b"\0\1" * 32000)  # 2 s
    job = ctx.store.add(source, min_speakers=1, max_speakers=2)
    assert _get(client, f"/jobs/{job.id}/audio/state").status_code == 404  # not done yet
    ctx.store.set_state(job.id, "done")
    ctx.scheduler.job_dir(job.id).mkdir(parents=True)

    state = _get(client, f"/jobs/{job.id}/audio/state").get_json()
    deadline = time.monotonic() + 30
    while state["state"] == "making" and time.monotonic() < deadline:
        time.sleep(0.1)
        state = _get(client, f"/jobs/{job.id}/audio/state").get_json()
    assert state["state"] == "ready", state

    with av.open(str(ctx.scheduler.job_dir(job.id) / "playback.opus")) as c:
        assert c.streams.audio[0].codec_context.name == "opus"
        assert c.duration / 1e6 == pytest.approx(2.0, abs=0.05)
    part = _get(client, f"/jobs/{job.id}/audio", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and len(part.data) == 100  # the web views seek this way

    moved = tmp / "moved.wav"
    moved.write_bytes(source.read_bytes())
    gone = ctx.store.add(moved, min_speakers=1, max_speakers=2)
    moved.unlink()
    ctx.store.set_state(gone.id, "done")
    state = _get(client, f"/jobs/{gone.id}/audio/state").get_json()
    assert state["state"] == "failed" and "no longer at" in state["message"]
