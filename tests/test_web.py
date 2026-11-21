# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The local web app: its access checks and the add-recordings flow (no window, no models)."""

import io
import json
import threading
import time
import wave
from dataclasses import replace

import av
import pytest

from wavematerial.config import Paths, load_settings
from wavematerial.jobs.scheduler import Scheduler
from wavematerial.jobs.store import JobStore
from wavematerial.models.installer import Installer
from wavematerial.models.manifest import load_manifest
from wavematerial.preflight import Device
from wavematerial.transcript.schema import Transcript, Turn, Word
from wavematerial.transcript.store import save_revision, write_artifact
from wavematerial.updates import UpdateChecker
from wavematerial.web import COOKIE, create_app
from wavematerial.web.context import AppContext, NativeHooks

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
    (folder / "notes.txt").write_text("not audio", encoding="utf-8")

    listed = _post(
        client, "/add/files", data={"how": "typed", "dropped": json.dumps([str(folder)])}
    )
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
    assert table.count('hx-swap-oob="true"') == 6  # summary, 4 chip counts, sidebar count
    assert '<a class="chip' not in table  # the chip links themselves are never replaced
    assert "2 recordings · 1 in progress" in table
    assert 'id="chip-count-done" class="chip-count" hx-swap-oob="true">1<' in table
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


def test_editor_opens_the_current_revision_and_only_for_done_jobs(web):
    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    source = tmp / "apollo11.wav"
    source.write_bytes(b"\0")
    job = ctx.store.add(source, min_speakers=1, max_speakers=2)
    assert _get(client, f"/jobs/{job.id}/edit").status_code == 302  # still queued

    job_dir = ctx.scheduler.job_dir(job.id)
    job_dir.mkdir(parents=True)
    turn = Turn("SPEAKER_00", (Word("Eagle", 1.0, 1.4), Word("landed", 1.5, 2.0)))
    original = Transcript("en", 3.0, ("SPEAKER_00",), (turn,))
    write_artifact(job_dir, original)
    edited = Turn(
        "SPEAKER_00", (Word("Eagle", 1.0, 1.4), Word("has", 1.5, 1.7), Word("landed", 1.7, 2.0))
    )
    save_revision(
        job_dir, replace(original, turns=(edited,), speaker_names={"SPEAKER_00": "Armstrong"})
    )
    ctx.store.set_state(job.id, "done")

    page = _get(client, f"/jobs/{job.id}/edit").get_data(as_text=True)
    data = json.loads(page.split('id="transcript-data">', 1)[1].split("</script>", 1)[0])
    assert data["names"] == {"SPEAKER_00": "Armstrong"}
    assert [w[0] for w in data["turns"][0]["words"]] == ["Eagle", "has", "landed"]

    (job_dir / "artifact.json").write_text("{not json", encoding="utf-8")
    broken = _get(client, f"/jobs/{job.id}/edit")
    assert broken.status_code == 200 and "can't be opened" in broken.get_data(as_text=True)


def test_autosave_writes_the_revision_and_outputs_and_refuses_bad_edits(web):
    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    source = tmp / "apollo11.wav"
    source.write_bytes(b"\0")
    job = ctx.store.add(source, min_speakers=1, max_speakers=2)
    job_dir = ctx.scheduler.job_dir(job.id)
    job_dir.mkdir(parents=True)
    turns = (
        Turn("SPEAKER_00", (Word("Houston,", 1.0, 1.5), Word("Tranquility", 1.6, 2.2))),
        Turn("SPEAKER_01", (Word("Roger.", 3.0, 3.4),)),
    )
    write_artifact(job_dir, Transcript("en", 5.0, ("SPEAKER_00", "SPEAKER_01"), turns))
    artifact = (job_dir / "artifact.json").read_bytes()
    ctx.store.set_state(job.id, "done")

    def save(body):
        return _post(client, f"/jobs/{job.id}/revision", json=body)

    def words(*ws):
        return [{"word": w, "start": s, "end": e} for w, s, e in ws]

    good = {
        "speakers": ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"],
        "names": {"SPEAKER_00": "Armstrong", "SPEAKER_02": "  "},
        "turns": [
            {
                "speaker": "SPEAKER_00",
                "words": words(
                    ("Houston,", 1.0, 1.5), ("Tranquility", 1.6, 1.9), ("Base", 1.9, 2.2)
                ),
            },
            {"speaker": "SPEAKER_02", "words": words(("Roger.", 3.0, 3.4))},
        ],
    }
    assert save(good).status_code == 200
    assert (job_dir / "artifact.json").read_bytes() == artifact
    txt = (job_dir / "outputs" / "transcript.txt").read_text(encoding="utf-8")
    assert txt == "Armstrong: Houston, Tranquility Base\n\nSPEAKER_02: Roger.\n\n"
    assert ctx.store.get(job.id).speakers == 2

    backwards = {
        **good,
        "turns": [{"speaker": "SPEAKER_00", "words": words(("a", 2.0, 2.1), ("b", 1.0, 1.1))}],
    }
    spaced = {**good, "turns": [{"speaker": "SPEAKER_00", "words": words(("two words", 1.0, 1.1))}]}
    stranger = {**good, "turns": [{"speaker": "SPEAKER_09", "words": words(("hi", 1.0, 1.1))}]}
    for bad in (backwards, spaced, stranger, {"turns": []}, None):
        assert save(bad).status_code == 422
    assert "Tranquility Base" in (job_dir / "outputs" / "transcript.txt").read_text(
        encoding="utf-8"
    )  # unchanged


def test_editor_turns_audio_off_where_the_window_would_crash_playing_it(web, monkeypatch):
    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    source = tmp / "apollo11.wav"
    source.write_bytes(b"\0")
    job = ctx.store.add(source, min_speakers=1, max_speakers=2)
    job_dir = ctx.scheduler.job_dir(job.id)
    job_dir.mkdir(parents=True)
    turn = Turn("SPEAKER_00", (Word("Eagle", 1.0, 1.4),))
    write_artifact(job_dir, Transcript("en", 3.0, ("SPEAKER_00",), (turn,)))
    ctx.store.set_state(job.id, "done")
    monkeypatch.setattr("wavematerial.web.views.window_audio_problem", lambda: "no audio sink")

    def audio_problem():
        page = _get(client, f"/jobs/{job.id}/edit").get_data(as_text=True)
        return json.loads(page.split('id="transcript-data">', 1)[1].split("</script>", 1)[0])[
            "audio_problem"
        ]

    assert audio_problem() is None  # a browser plays audio its own way
    ctx.native = NativeHooks(pick_files=lambda: [])  # the app window (WebKitGTK on Linux)
    assert audio_problem() == "no audio sink"


def test_renaming_a_recording_and_fetching_its_original_transcript(web):
    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    source = tmp / "apollo11.wav"
    source.write_bytes(b"\0")
    job = ctx.store.add(source, min_speakers=1, max_speakers=2)
    job_dir = ctx.scheduler.job_dir(job.id)
    job_dir.mkdir(parents=True)
    original = Transcript(
        "en", 3.0, ("SPEAKER_00",), (Turn("SPEAKER_00", (Word("Eagle", 1.0, 1.4),)),)
    )
    write_artifact(job_dir, original)
    save_revision(
        job_dir, replace(original, turns=(Turn("SPEAKER_00", (Word("Falcon", 1.0, 1.4),)),))
    )
    ctx.store.set_state(job.id, "done")

    assert "<title>apollo11 · WaveMaterial" in _get(client, f"/jobs/{job.id}/edit").get_data(
        as_text=True
    )
    assert _post(client, f"/jobs/{job.id}/rename", data={"name": "  "}).status_code == 422
    r = _post(client, f"/jobs/{job.id}/rename", data={"name": "  Apollo 11  landing v1.2 "})
    assert r.get_json()["name"] == "Apollo 11 landing v1.2"
    page = _get(client, f"/jobs/{job.id}/edit").get_data(as_text=True)
    assert "<title>Apollo 11 landing v1.2 · WaveMaterial" in page  # not cut at the dot
    assert ">Apollo 11 landing v1.2<" in page  # the Recent list too

    orig = _get(client, f"/jobs/{job.id}/original").get_json()
    assert orig["turns"][0]["words"][0][0] == "Eagle" and orig["names"] == {}


def test_export_downloads_in_a_browser_and_saves_through_the_window(web):
    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    source = tmp / "media" / "apollo11.wav"
    source.parent.mkdir()
    source.write_bytes(b"\0")
    job = ctx.store.add(source, min_speakers=1, max_speakers=2)
    job_dir = ctx.scheduler.job_dir(job.id)
    job_dir.mkdir(parents=True)
    turn = Turn("SPEAKER_00", (Word("Tranquility", 1.0, 1.6), Word("Base.", 1.6, 2.0)))
    t = Transcript("en", 3.0, ("SPEAKER_00",), (turn,))
    write_artifact(job_dir, t)
    save_revision(job_dir, replace(t, speaker_names={"SPEAKER_00": "Armstrong"}))
    ctx.store.set_state(job.id, "done")
    ctx.store.update(job.id, name='Apollo 11: "landing"')

    r = _get(client, f"/jobs/{job.id}/export/txt")
    assert r.data == b"Armstrong: Tranquility Base.\n\n"
    assert "Apollo%2011_%20_landing_.txt" in r.headers["Content-Disposition"]  # safe file name
    assert _get(client, f"/jobs/{job.id}/export/exe").status_code == 404

    assert _post(client, f"/jobs/{job.id}/export/srt").status_code == 400  # no window
    asked = []
    target = tmp / "out" / "landing.srt"
    target.parent.mkdir()
    ctx.native = NativeHooks(
        pick_files=lambda: [],
        save_file=lambda name, folder: asked.append((name, folder)) or str(target),
    )
    assert _post(client, f"/jobs/{job.id}/export/srt").get_json() == {"path": str(target)}
    assert asked == [("Apollo 11_ _landing_.srt", str(source.parent))]  # starts by the recording
    assert "Armstrong: Tranquility Base." in target.read_text(encoding="utf-8")
    assert ctx.settings().export_dir == str(target.parent)  # remembered for next time
    ctx.native = NativeHooks(
        pick_files=lambda: [], save_file=lambda name, folder: asked.append(folder)
    )
    assert _post(client, f"/jobs/{job.id}/export/vtt").get_json() == {"cancelled": True}
    assert asked[-1] == str(target.parent)


def test_docx_and_pdf_exports_carry_the_transcript():
    docx = pytest.importorskip("docx")
    pytest.importorskip("reportlab")
    from wavematerial.transcript import export

    turn = Turn(
        "SPEAKER_00",
        (Word("Jawaharlal", 1.0, 1.6), Word("Nehru,", 1.6, 2.0), Word("Śāstrī.", 2.0, 2.5)),
    )
    t = Transcript("en", 3.0, ("SPEAKER_00",), (turn,), speaker_names={"SPEAKER_00": "Interviewer"})
    assert {"docx", "pdf"} <= set(export.available())
    assert export.file_name("con", "txt") == "_con.txt"  # a Windows device name
    assert export.file_name("Lpt1.final ", "pdf") == "_Lpt1.final.pdf"
    assert export.file_name("Interview... ", "txt") == "Interview.txt"
    doc = docx.Document(io.BytesIO(export.render("docx", t, "Interview")))
    assert [p.text for p in doc.paragraphs] == [
        "Interview",
        "Interviewer: Jawaharlal Nehru, Śāstrī.",
    ]
    pdf = export.render("pdf", t, "Interview")
    assert pdf.startswith(b"%PDF") and b"NotoSans" in pdf  # the embedded font covers ā and ś
    assert export.render("pdf", t, "Interview") == pdf  # reproducible


def test_quit_closes_the_window_or_stops_the_browser_mode_and_heartbeats_count(web):
    ctx, client, _ = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    ctx.installer.all_installed = lambda: True
    assert "Quit WaveMaterial" in _get(client, "/library").get_data(as_text=True)  # no window
    ctx.last_seen = 0.0
    assert _get(client, "/alive").status_code == 204 and ctx.last_seen > 0
    r = _post(client, "/quit")
    assert "WaveMaterial has closed" in r.get_data(as_text=True)
    assert ctx.quit.wait(2)  # the app is told to stop just after answering
    closed = threading.Event()
    ctx.native = NativeHooks(pick_files=lambda: [], close=closed.set)  # the app window
    assert "Quit WaveMaterial" in _get(client, "/library").get_data(as_text=True)
    _post(client, "/quit")
    assert closed.wait(2)  # in the window, Quit closes it (the app then shuts down)
