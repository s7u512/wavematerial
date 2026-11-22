# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The local web app: its access checks and the add-recordings flow (no window, no models)."""

import io
import json
import threading
import time
import wave
from dataclasses import replace
from types import SimpleNamespace

import av
import pytest

from wavematerial.config import Paths, load_settings
from wavematerial.jobs.scheduler import Scheduler
from wavematerial.jobs.store import JobStore
from wavematerial.models.installer import Installer
from wavematerial.models.manifest import load_manifest
from wavematerial.preflight import Device
from wavematerial.transcript.render import write_outputs
from wavematerial.transcript.schema import Transcript, Turn, Word
from wavematerial.transcript.store import read_artifact, save_revision, write_artifact
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


def test_packaged_runtime_shows_its_built_in_libraries_licences(tmp_path, monkeypatch):
    from wavematerial.web import credits

    (tmp_path / "licenses").mkdir()
    for name, text in [("openssl-3", "Apache"), ("cpython", "PSF"), ("zlib", "zlib")]:
        (tmp_path / "licenses" / f"LICENSE.{name}.txt").write_text(text, encoding="utf-8")
    monkeypatch.setattr(credits.sys, "base_prefix", str(tmp_path))
    text = credits.licence_text("python")
    assert text.index("LICENSE.cpython.txt") < text.index("LICENSE.openssl-3.txt")
    assert "Apache" in text and "zlib" in text


def test_packaged_runtime_lists_its_vendored_libraries(tmp_path, monkeypatch):
    from wavematerial.web import credits

    vendored = tmp_path / "licenses" / "vendored"
    (vendored / "x264").mkdir(parents=True)
    (vendored / "x264" / "COPYING").write_text("GNU GPL v2", encoding="utf-8")
    entry = {"name": "x264", "version": "b35605a", "licence": "GPL-2.0-or-later", "key": "x264"}
    (vendored / "components.json").write_text(json.dumps([entry]), encoding="utf-8")
    monkeypatch.setattr(credits.sys, "base_prefix", str(tmp_path))
    names = [c.name for c in credits.bundled()]
    assert "x264" in names and not any("inside PyAV" in n for n in names)
    assert "GNU GPL v2" in credits.licence_text("vendored/x264")
    assert credits.licence_text("vendored/../licenses") is None


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
    # summary, Start all, 5 chip counts, the sidebar's count and Editor item
    assert table.count('hx-swap-oob="true"') == 9
    assert '<a class="chip' not in table  # the chip links themselves are never replaced
    assert "2 recordings · 1 in progress" in table
    assert 'id="chip-count-done" class="chip-count" hx-swap-oob="true">1<' in table
    assert 'id="nav-library-count" class="nav-count" hx-swap-oob="true">2<' in table


def test_add_to_library_waits_for_start_and_start_all_keeps_the_order(web):
    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    names = ("apollo11.wav", "gemini4.wav", "apollo8.wav")
    for name in names:
        (tmp / name).write_bytes(b"\0")
    running = ctx.store.add(tmp / "apollo11.wav", min_speakers=1, max_speakers=2)

    # "Add to library" sends start=0; the form's own submit ("Add and transcribe") doesn't.
    for name in names[1:]:
        _post(client, "/add", data={"paths": [str(tmp / name)], "start": "0"})
    new = [j for j in ctx.store.all() if j.state == "new"]
    assert [j.name for j in new] == ["gemini4.wav", "apollo8.wav"]
    page = _get(client, "/library/table").get_data(as_text=True)  # with the header's parts
    assert "Start 2 not started" in page and "2 not started" in page
    assert page.index("gemini4.wav") < page.index("apollo11.wav")  # waiting for you: first

    _post(client, f"/jobs/{new[1].id}/start")  # one row's Start: to the end of the queue
    _post(client, "/jobs/start-all")
    queued = sorted((j for j in ctx.store.all() if j.state == "queued"), key=lambda j: j.position)
    assert [j.id for j in queued] == [running.id, new[1].id, new[0].id]
    assert "not started" not in _get(client, "/library/table").get_data(as_text=True)


def test_the_sidebar_editor_reopens_the_last_opened_transcript(web, apollo):
    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    assert _get(client, "/editor").headers["Location"] == "/library"  # nothing done yet
    assert "No transcripts yet" in _get(client, "/library/table").get_data(as_text=True)

    jobs = []
    for name in ("apollo11.wav", "gemini4.wav"):
        (tmp / name).write_bytes(b"\0")
        job = ctx.store.add(tmp / name, min_speakers=1, max_speakers=2)
        write_artifact(ctx.scheduler.job_dir(job.id), apollo)
        ctx.store.set_state(job.id, "done")
        jobs.append(job)
    first, second = jobs
    ctx.store.update(second.id, finished_at="2099-01-01T00:00:00+00:00")
    # Never opened: the newest finished one.
    assert _get(client, "/editor").headers["Location"] == f"/jobs/{second.id}/edit"

    page = _get(client, f"/jobs/{first.id}/edit").get_data(as_text=True)
    assert 'id="nav-editor" class="nav-item is-active"' in page  # lit in the editor
    assert _get(client, "/editor").headers["Location"] == f"/jobs/{first.id}/edit"
    assert "Last: apollo11" in _get(client, "/library/table").get_data(as_text=True)

    _post(client, f"/jobs/{first.id}/delete")  # gone: back to the newest finished one
    assert _get(client, "/editor").headers["Location"] == f"/jobs/{second.id}/edit"


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
        "",
        "Speakers: Interviewer",
        "Duration: 0:03",
        "",
        "TRANSCRIPT",
        "",
        "Interviewer: Jawaharlal Nehru, Śāstrī.",
    ]
    centre, justify = 1, 3  # WD_ALIGN_PARAGRAPH
    assert [doc.paragraphs[i].alignment for i in (0, 5, 7)] == [centre, centre, justify]
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


def test_interface_preferences_are_saved_and_bad_values_ignored(web):
    ctx, client, _ = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    body = {"dismiss_tip": "shift-select", "sidebar_width": 300, "panel_width": 9999}
    assert _post(client, "/settings/ui", json=body).status_code == 204
    _post(client, "/settings/ui", json={"dismiss_tip": "shift-select"})  # no duplicate
    s = ctx.settings()
    assert s.dismissed_tips == ["shift-select"]
    assert (s.sidebar_width, s.panel_width) == (300, 0)  # 9999 is out of range: ignored


def test_sidebar_search_finds_titles_and_transcript_text(web):
    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    for name, word in (("apollo11.wav", "Tranquility"), ("gemini4.wav", "spacewalk")):
        source = tmp / name
        source.write_bytes(b"\0")
        job = ctx.store.add(source, min_speakers=1, max_speakers=2)
        job_dir = ctx.scheduler.job_dir(job.id)
        job_dir.mkdir(parents=True)
        t = Transcript("en", 3.0, ("SPEAKER_00",), (Turn("SPEAKER_00", (Word(word, 1.0, 1.5),)),))
        write_artifact(job_dir, t)
        write_outputs(job_dir, t)
        ctx.store.set_state(job.id, "done")

    def found(q):
        return _get(client, "/sidebar/search", query_string={"q": q}).get_data(as_text=True)

    assert "gemini4" in found("GEMINI") and "apollo11" not in found("GEMINI")  # title
    assert "apollo11" in found("tranquil") and "gemini4" not in found("tranquil")  # text
    assert "No matches" in found("zzz")
    assert "Recent" in found("")


def test_history_saves_versions_and_an_automatic_one_on_opening(web):
    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    source = tmp / "apollo11.wav"
    source.write_bytes(b"\0")
    job = ctx.store.add(source, min_speakers=1, max_speakers=2)
    job_dir = ctx.scheduler.job_dir(job.id)
    job_dir.mkdir(parents=True)
    t = Transcript("en", 3.0, ("SPEAKER_00",), (Turn("SPEAKER_00", (Word("Eagle", 1.0, 1.5),)),))
    write_artifact(job_dir, t)
    ctx.store.set_state(job.id, "done")

    def listing():
        return _get(client, f"/jobs/{job.id}/versions").get_json()

    _get(client, f"/jobs/{job.id}/edit")
    assert listing() == []  # nothing edited yet: no automatic version

    def edit(word):
        save_revision(job_dir, replace(t, turns=(Turn("SPEAKER_00", (Word(word, 1.0, 1.5),)),)))

    edit("Falcon")
    _get(client, f"/jobs/{job.id}/edit")
    _get(client, f"/jobs/{job.id}/edit")  # unchanged since: no second one
    assert [(v["name"], v["auto"]) for v in listing()] == [("When opened", True)]

    assert _post(client, f"/jobs/{job.id}/versions", json={"name": " "}).status_code == 422
    vid = _post(client, f"/jobs/{job.id}/versions", json={"name": "after first pass"}).get_json()[
        "id"
    ]
    for word in ("Columbia", "Orion", "Aquarius", "Intrepid"):
        edit(word)
        _get(client, f"/jobs/{job.id}/edit")
    versions_now = listing()
    assert sum(v["auto"] for v in versions_now) == 3  # only the newest automatic ones are kept
    assert any(v["name"] == "after first pass" for v in versions_now)  # named ones stay

    auto_id = next(v["id"] for v in listing() if v["auto"])
    assert (
        _post(client, f"/jobs/{job.id}/versions/{auto_id}/rename", json={"name": " "}).status_code
        == 422
    )
    r = _post(client, f"/jobs/{job.id}/versions/{auto_id}/rename", json={"name": "  kept  this "})
    assert r.get_json() == {"name": "kept this"}
    renamed = next(v for v in listing() if v["id"] == auto_id)
    assert (renamed["name"], renamed["auto"]) == ("kept this", False)  # now a named version
    saved = _get(client, f"/jobs/{job.id}/versions/{vid}").get_json()
    assert saved["turns"][0]["words"][0][0] == "Falcon"
    _post(client, f"/jobs/{job.id}/versions/{vid}/delete")
    assert _get(client, f"/jobs/{job.id}/versions/{vid}").status_code == 404
    assert (job_dir / "artifact.json").exists() and read_artifact(job_dir) == t  # untouched


def test_transcribe_again_queues_a_new_entry_beside_the_old_one(web):
    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    source = tmp / "apollo11.wav"
    source.write_bytes(b"\0")
    job = ctx.store.add(source, min_speakers=2, max_speakers=3, key_terms=("Eagle",))
    ctx.store.set_state(job.id, "done")
    dialog = _get(client, f"/jobs/{job.id}/again").get_data(as_text=True)
    assert "apollo11 (2)" in dialog and "Eagle" in dialog  # the old settings, prefilled

    r = _post(
        client,
        f"/jobs/{job.id}/again",
        data={"min_speakers": "3", "max_speakers": "2", "key_terms": ["Tranquility"]},
    )
    assert r.status_code == 200
    new = max(ctx.store.all(), key=lambda j: j.id)
    assert (new.name, new.state, new.source) == ("apollo11 (2)", "queued", source)
    assert (new.min_speakers, new.max_speakers, new.key_terms) == (2, 3, ("Tranquility",))
    assert ctx.store.get(job.id).state == "done"  # the old entry is untouched
    ctx.store.set_state(new.id, "done")
    _post(client, f"/jobs/{new.id}/again", data={"min_speakers": "2", "max_speakers": "3"})
    assert max(ctx.store.all(), key=lambda j: j.id).name == "apollo11 (3)"  # not "(2) (2)"

    source.unlink()
    assert "no longer at" in _get(client, f"/jobs/{job.id}/again").get_data(as_text=True)
    assert _post(client, f"/jobs/{job.id}/again", data={}).status_code == 409


def test_a_passage_is_transcribed_again_only_while_the_queue_is_idle(web, monkeypatch):
    import sys

    from wavematerial.jobs import passage

    ctx, client, tmp = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    source = tmp / "apollo11.wav"
    source.write_bytes(b"\0")
    job = ctx.store.add(source, min_speakers=1, max_speakers=2)
    ctx.scheduler.job_dir(job.id).mkdir(parents=True)
    ctx.store.set_state(job.id, "done")
    # A stand-in for the engine: it answers with one word over the selection, after a moment.
    fake = (
        "import json, sys, time; s = json.loads(sys.argv[1]); time.sleep(0.3); "
        "open(s['out'], 'w').write(json.dumps({'words': [['Eagle', s['start'], s['end']]]}))"
    )
    monkeypatch.setattr(passage, "RUNNER", [sys.executable, "-c", fake])

    ctx.scheduler._current = 99  # a job is being transcribed
    r = _post(client, f"/jobs/{job.id}/passage", json={"start": 1.0, "end": 2.0})
    assert (
        r.status_code == 409 and not _get(client, f"/jobs/{job.id}/passage").get_json()["available"]
    )
    ctx.scheduler._current = None

    assert (
        _post(client, f"/jobs/{job.id}/passage", json={"start": 1.0, "end": 2.0}).status_code == 200
    )
    assert not ctx.scheduler.try_hold()  # the queue is held while it runs
    state = _get(client, f"/jobs/{job.id}/passage").get_json()
    deadline = time.monotonic() + 10
    while state.get("state") == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        state = _get(client, f"/jobs/{job.id}/passage").get_json()
    assert state["state"] == "done" and state["words"] == [["Eagle", 1.0, 2.0]]
    assert state["available"] and ctx.scheduler.try_hold()  # released afterwards
    ctx.scheduler.release_hold()


def test_the_app_opens_on_the_landing_screen_once_set_up(web):
    ctx, client, _ = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    r = _get(client, "/")
    assert r.status_code == 302 and r.headers["Location"] == "/setup"  # models not in yet
    ctx.installer.all_installed = lambda: True
    page = _get(client, "/").get_data(as_text=True)
    assert "Vulkan-first transcription" in page and 'href="/library"' in page
    assert 'class="sidebar"' not in page  # minimal: no sidebar
    assert 'hx-get="/add"' in page and 'hx-post="/quit"' in page  # quick start, and Quit
    landing = {"HX-Current-URL": "http://127.0.0.1:5555/"}
    assert _post(client, "/add", data={}, headers=landing).headers.get("HX-Redirect") == "/library"
    library = {"HX-Current-URL": "http://127.0.0.1:5555/library"}
    assert "HX-Redirect" not in _post(client, "/add", data={}, headers=library).headers


def test_copy_log_gives_a_report_without_the_home_folder(web, monkeypatch):
    from wavematerial import __version__

    ctx, client, tmp_path = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    home = tmp_path / "home" / "someone"
    monkeypatch.setattr("wavematerial.jobs.report.Path.home", lambda: home)
    source = home / "Recordings" / "apollo11.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"RIFF" + bytes(64))
    job = ctx.store.add(source, min_speakers=2, max_speakers=3)
    job_dir = ctx.scheduler.job_dir(job.id)
    job_dir.mkdir(parents=True)
    lines = [f"line {i} reading {source}" for i in range(250)]
    (job_dir / "worker.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    r = _get(client, f"/jobs/{job.id}/report")
    text = r.get_data(as_text=True)
    assert r.status_code == 200 and r.mimetype == "text/plain"
    assert text.startswith(f"WaveMaterial {__version__} · ")
    assert "apollo11.wav" in text and "2–3 speakers" in text
    assert str(home) not in text and "~/Recordings/apollo11.wav" in text
    assert "line 49 " not in text and "line 50 " in text and "line 249 " in text  # last 200


def _setup_client(web, monkeypatch, free=10**12):
    ctx, client, tmp_path = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    started = []
    monkeypatch.setattr(ctx.installer, "start", lambda: started.append(1))
    monkeypatch.setattr("wavematerial.models.folders.free_space", lambda folder: free)
    return ctx, client, tmp_path, started


def test_setup_downloads_nothing_until_the_button_is_clicked(web, monkeypatch):
    ctx, client, _, started = _setup_client(web, monkeypatch)
    page = _get(client, "/setup").get_data(as_text=True)
    assert "Download models" in page and "2.9 GB on disk (a 2.7 GB download)" in page
    assert "huggingface.co" in page and not started
    _post(client, "/setup/start")
    assert started


def test_setup_refuses_to_start_without_room(web, monkeypatch):
    ctx, client, _, started = _setup_client(web, monkeypatch, free=1_200_000_000)
    page = _post(client, "/setup/start").get_data(as_text=True)
    assert "needs 3.7 GB free on this drive and it has 1.2 GB" in page and not started


def test_setup_resumes_a_started_download_in_the_same_folder(web, monkeypatch):
    ctx, client, _, started = _setup_client(web, monkeypatch)
    ctx.native = NativeHooks(pick_folder=lambda: "/elsewhere")
    downloads = ctx.models_dir() / ".downloads"
    downloads.mkdir(parents=True)
    (downloads / f"{ctx.manifest[0].id}.part").write_bytes(b"0" * 1000)
    page = _get(client, "/setup").get_data(as_text=True)
    assert "Resume download" in page and "left to download" in page
    assert "Change folder" not in page  # the partial files stay where they are


def test_choosing_a_folder_makes_a_models_subfolder_and_notes_it(web, monkeypatch):
    ctx, client, tmp_path, _ = _setup_client(web, monkeypatch)
    drive = tmp_path / "D"
    drive.mkdir()
    ctx.native = NativeHooks(pick_folder=lambda: str(drive))
    _post(client, "/setup/folder")
    target = drive / "WaveMaterial models"
    assert load_settings(ctx.paths.settings_file).models_dir == str(target)
    note = (ctx.paths.data_dir / "models-folder.txt").read_text(encoding="utf-8-sig")
    assert note.strip() == str(target)


def test_setup_says_when_the_chosen_models_folder_is_gone(web, monkeypatch):
    ctx, client, tmp_path, started = _setup_client(web, monkeypatch)
    gone = tmp_path / "unplugged" / "WaveMaterial models"
    ctx.save_settings(replace(ctx.settings(), models_dir=str(gone)))
    page = _get(client, "/setup").get_data(as_text=True)
    assert "available. Reconnect the drive" in page and "disabled" in page
    _post(client, "/setup/start")
    assert not started


def test_remove_downloaded_models_then_back_to_setup(web, monkeypatch):
    ctx, client, _, _ = _setup_client(web, monkeypatch)
    for m in ctx.manifest:
        m.folder(ctx.models_dir()).mkdir(parents=True)
    monkeypatch.setattr(ctx.scheduler, "try_hold", lambda: False)  # a transcription runs
    page = _post(client, "/settings/remove-models").get_data(as_text=True)
    assert (
        "A transcription is running" in page and ctx.manifest[0].folder(ctx.models_dir()).exists()
    )

    monkeypatch.setattr(ctx.scheduler, "try_hold", lambda: True)
    monkeypatch.setattr(ctx.scheduler, "release_hold", lambda: None)
    r = _post(client, "/settings/remove-models")
    assert r.headers["HX-Redirect"] == "/setup"
    assert not any(m.folder(ctx.models_dir()).exists() for m in ctx.manifest)


def test_an_update_waits_for_the_queue_then_holds_it_and_quits(web, monkeypatch):
    from wavematerial.web import views

    ctx, _, _ = web
    closed, marked = threading.Event(), []
    ctx.native = NativeHooks(close=closed.set)
    ctx.updater = SimpleNamespace(cancelled=False, mark_ready=lambda: marked.append(1))
    real_sleep = time.sleep
    monkeypatch.setattr(views.time, "sleep", lambda s: real_sleep(0.01))
    busy = [True, True, False]  # a transcription is running for the first two looks
    monkeypatch.setattr(ctx.scheduler, "try_hold", lambda: not busy.pop(0))

    views._install_when_free(ctx)
    assert marked and closed.wait(5)


def test_the_update_buttons_explain_themselves(web, monkeypatch):
    from wavematerial import updater as up
    from wavematerial.updates import UpdateStatus

    ctx, client, tmp_path = web
    client.set_cookie(COOKIE, "secret-token", domain="127.0.0.1")
    ctx.updates.status = UpdateStatus(checked_at="2026-11-22T00:00:00+00:00", latest="99.0.0")
    ctx.updater = up.Updater(tmp_path / "cache", up.Install("tarball", tmp_path / "app"))
    page = _get(client, "/settings").get_data(as_text=True)
    assert "Self-update" in page and "Manual update" in page
    assert 'role="tooltip"' in page and "Only saves the new version to your Downloads" in page
    monkeypatch.setattr(ctx.installer, "all_installed", lambda: True)
    library = _get(client, "/library").get_data(as_text=True)
    assert "WaveMaterial 99.0.0 is available" in library  # the sidebar notice
