# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The local web app: its access checks and the add-recordings flow (no window, no models)."""

import wave

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
