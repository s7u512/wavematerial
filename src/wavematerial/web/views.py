# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Pages and htmx fragments: first run, library, add recordings, job details, settings."""

from __future__ import annotations

import json
import logging
import shutil
import threading
import webbrowser
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
)

from wavematerial.engine.playback import PLAYBACK
from wavematerial.jobs.events import STAGE_LABELS, read_events, stage_times
from wavematerial.jobs.store import Job
from wavematerial.models.download import is_installed, verify
from wavematerial.preflight import choose, usable_gpus
from wavematerial.transcript import export
from wavematerial.transcript.render import write_outputs
from wavematerial.transcript.schema import TranscriptError
from wavematerial.transcript.store import (
    REVISION,
    edited_transcript,
    read_artifact,
    read_current,
    save_revision,
)
from wavematerial.updates import RELEASES_PAGE
from wavematerial.web import credits, format
from wavematerial.web.context import AppContext, open_path
from wavematerial.web.icons import FILLED, ICONS
from wavematerial.web.media import window_audio_problem

log = logging.getLogger(__name__)

MEDIA = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wma", ".aiff", ".aif",
    ".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".3gp", ".amr", ".mpg", ".mpeg", ".ts",
}  # fmt: skip

# Model groups as the screens show them.
SETUP_GROUPS = [
    ("Transcription text · Qwen3-ASR 1.7B", ["qwen3-asr-1.7b-q8_0"]),
    ("Word timings · Parakeet TDT 0.6B", ["parakeet-tdt-0.6b-v3-int8"]),
    ("Speaker detection models", ["silero-vad", "pyannote-segmentation-3.0", "titanet-small"]),
]
SETTINGS_GROUPS = [
    ("Qwen3-ASR 1.7B", "Transcription text", ["qwen3-asr-1.7b-q8_0"]),
    ("Parakeet TDT 0.6B v3", "Word timings", ["parakeet-tdt-0.6b-v3-int8"]),
    ("Speaker models", "Segmentation + voice embeddings",
     ["pyannote-segmentation-3.0", "titanet-small"]),
    ("Silero VAD", "Speech detection", ["silero-vad"]),
]  # fmt: skip

FILTERS = {
    "all": ("All", None),
    "progress": ("In progress", {"queued", "running", "cancelled"}),
    "done": ("Done", {"done"}),
    "failed": ("Failed", {"failed"}),
}


def _ctx() -> AppContext:
    return g.ctx


# ---- view models -------------------------------------------------------------------------


@dataclass
class Row:
    job: Job
    status: str  # pill class: running, queued, done, failed, cancelled
    label: str
    note: str
    detail: str
    speakers: str
    length: str
    added: str
    percent: int


def _job_note(ctx: AppContext, job: Job) -> str:
    if job.state != "done":
        return job.error or ""
    rev = ctx.scheduler.job_dir(job.id) / REVISION
    if not rev.exists():
        return ""
    try:
        names = json.loads(rev.read_text(encoding="utf-8")).get("speaker_names") or {}
    except (OSError, json.JSONDecodeError):
        names = {}
    return "speakers named" if names else "edited"


def _chunks(ctx: AppContext, job: Job) -> int | None:
    try:
        return len(json.loads((ctx.scheduler.job_dir(job.id) / "chunks.json").read_text()))
    except (OSError, json.JSONDecodeError):
        return None


def _running_detail(ctx: AppContext, job: Job) -> tuple[str, str]:
    """('Text · chunk 37 of 64', 'about 4 min left')."""
    stage = STAGE_LABELS.get(job.stage or "", "Starting")
    if job.stage == "text":
        n = _chunks(ctx, job)
        if n:
            stage = f"Text · chunk {max(1, round(job.stage_fraction * n))} of {n}"
    elapsed = format.elapsed_since(job.started_at)
    left = None
    if elapsed and job.progress > 0.05:
        left = elapsed / job.progress - elapsed
    return stage, format.time_left(left)


def _row(ctx: AppContext, job: Job, first_queued: int | None) -> Row:
    if job.speakers is not None:
        speakers = str(job.speakers)
    elif job.min_speakers == job.max_speakers:
        speakers = str(job.min_speakers)
    else:
        speakers = f"{job.min_speakers}–{job.max_speakers}"
    label, detail = {
        "running": ("Transcribing", ""),
        "queued": ("Queued · next" if job.id == first_queued else "Queued", ""),
        "done": ("Ready", ""),
        "failed": ("Failed", ""),
        "cancelled": ("Stopped", ""),
    }[job.state]
    if job.state == "running":
        stage, left = _running_detail(ctx, job)
        detail = " · ".join(p for p in (stage, left) if p)
    return Row(
        job=job,
        status=job.state,
        label=label,
        note=_job_note(ctx, job),
        detail=detail,
        speakers=speakers,
        length=format.length(job.duration),
        added=format.added(job.created_at),
        percent=round(job.progress * 100),
    )


def _matches(ctx: AppContext, job: Job, q: str) -> bool:
    if not q:
        return True
    q = q.lower()
    if q in job.name.lower():
        return True
    if job.state == "done":
        txt = ctx.scheduler.job_dir(job.id) / "outputs" / "transcript.txt"
        try:
            return q in txt.read_text(encoding="utf-8").lower()
        except OSError:
            return False
    return False


def _library(ctx: AppContext, flt: str, q: str) -> dict:
    jobs = ctx.store.all()
    counts = {
        key: sum(1 for j in jobs if states is None or j.state in states)
        for key, (_, states) in FILTERS.items()
    }
    states = FILTERS.get(flt, FILTERS["all"])[1]
    queued = [j for j in jobs if j.state == "queued"]
    first_queued = queued[0].id if queued else None
    shown = [j for j in jobs if (states is None or j.state in states) and _matches(ctx, j, q)]
    # Newest first, except that unfinished work stays on top in queue order.
    active = [j for j in shown if j.state in ("running", "queued")]
    active.sort(key=lambda j: (j.state != "running", j.position))
    rest = sorted((j for j in shown if j not in active), key=lambda j: j.created_at, reverse=True)
    return {
        "rows": [_row(ctx, j, first_queued) for j in active + rest],
        "counts": counts,
        "flt": flt if flt in FILTERS else "all",
        "q": q,
        "filters": FILTERS,
        "total": len(jobs),
        "in_progress": sum(1 for j in jobs if j.state in ("running", "queued")),
    }


def _engine(ctx: AppContext) -> dict:
    jobs = ctx.store.all()
    running = next((j for j in jobs if j.state == "running"), None)
    waiting = sum(1 for j in jobs if j.state == "queued")
    choice = choose(
        ctx.devices,
        ctx.settings(),
        cores=ctx.cores,
        wsl=ctx.wsl,
        unreliable=ctx.store.unreliable_gpus(),
    )
    if running and running.device:
        device = running.device
        backend = "Vulkan" if "(vulkan)" in device else "Processor"
        name = format.short_device(device.rsplit(" (", 1)[0])
    else:
        backend = "Vulkan" if choice.backend == "vulkan" else "Processor"
        name = format.short_device(choice.description)
    return {
        "running": running,
        "paused": ctx.scheduler.paused,
        "position": f"1 of {waiting + 1}" if running else "",
        "device": f"{name} · {backend}",
    }


def _recent(ctx: AppContext) -> list[Job]:
    done = [j for j in ctx.store.all() if j.state == "done"]
    return sorted(done, key=lambda j: j.finished_at or "", reverse=True)[:4]


def _shell(ctx: AppContext, active: str) -> dict:
    return {
        "active": active,
        "recent": _recent(ctx),
        "engine": _engine(ctx),
        "library_count": len(ctx.store.all()),
    }


# ---- first run -----------------------------------------------------------------------------


def _device_banner(ctx: AppContext) -> dict:
    choice = choose(ctx.devices, ctx.settings(), cores=ctx.cores, wsl=ctx.wsl)
    if choice.backend == "vulkan":
        return {
            "ok": True,
            "title": "Fast mode available",
            "text": f"Using your {format.short_device(choice.description, keep_vendor=True)}"
            " graphics (Vulkan).",
        }
    return {"ok": False, "title": "Running on the processor", "text": choice.reason}


def _setup_state(ctx: AppContext) -> dict:
    inst = ctx.installer
    by_id = {m.id: m for m in ctx.manifest}
    groups = []
    for label, ids in SETUP_GROUPS:
        specs = [by_id[i] for i in ids]
        total = sum(s.size for s in specs)
        done = sum(inst.bytes_done(s) for s in specs)
        ready = all(is_installed(s, ctx.models_dir()) for s in specs)
        groups.append(
            {"label": label, "total": total, "done": done, "ready": ready,
             "percent": round(100 * done / total) if total else 100}
        )  # fmt: skip
    total, done = inst.total_size(), inst.total_done()
    return {
        "groups": groups,
        "total": format.size(total),
        "done": format.size(done),
        "percent": round(100 * done / total) if total else 100,
        "state": inst.state,
        "error": inst.error,
        "left": format.time_left(inst.seconds_left()),
        "size_total": format.size(total).replace(".00", ""),
    }


# ---- routes ----------------------------------------------------------------------------------


def register(app: Flask) -> None:
    app.jinja_env.globals.update(
        fmt=format, stage_labels=STAGE_LABELS, ICONS=ICONS, FILLED_ICONS=FILLED
    )

    @app.get("/")
    def home():
        ctx = _ctx()
        return redirect("/library" if ctx.installer.all_installed() else "/setup")

    # first run
    @app.get("/setup")
    def setup():
        ctx = _ctx()
        if ctx.installer.all_installed():
            return redirect("/library")
        if ctx.installer.state in ("idle",):
            ctx.installer.start()
        return render_template("setup.html", banner=_device_banner(ctx), s=_setup_state(ctx))

    @app.get("/setup/progress")
    def setup_progress():
        ctx = _ctx()
        if ctx.installer.all_installed():
            resp = make_response("")
            resp.headers["HX-Redirect"] = "/library"
            return resp
        return render_template("_setup_progress.html", s=_setup_state(ctx))

    @app.post("/setup/<action>")
    def setup_action(action: str):
        ctx = _ctx()
        if action == "pause":
            ctx.installer.pause()
        elif action in ("resume", "retry"):
            ctx.installer.start()
        else:
            abort(404)
        return render_template("_setup_progress.html", s=_setup_state(ctx))

    # library
    @app.get("/library")
    def library():
        ctx = _ctx()
        if not ctx.installer.all_installed():
            return redirect("/setup")
        data = _library(ctx, request.args.get("filter", "all"), request.args.get("q", ""))
        return render_template("library.html", **_shell(ctx, "library"), **data)

    @app.get("/library/table")
    def library_table():
        ctx = _ctx()
        data = _library(ctx, request.args.get("filter", "all"), request.args.get("q", ""))
        return render_template("_library_table.html", **data, oob=True)

    @app.get("/engine")
    def engine():
        return render_template("_engine.html", engine=_engine(_ctx()))

    @app.post("/queue/<action>")
    def queue(action: str):
        ctx = _ctx()
        if action == "pause":
            ctx.scheduler.pause()
        elif action == "resume":
            ctx.scheduler.resume_queue()
        else:
            abort(404)
        return render_template("_engine.html", engine=_engine(ctx))

    # job details
    def _drawer_data(ctx: AppContext, job_id: int) -> dict:
        try:
            job = ctx.store.get(job_id)
        except KeyError:
            abort(404)
        job_dir = ctx.scheduler.job_dir(job_id)
        times = stage_times(job_dir)
        n_chunks = _chunks(ctx, job)
        order = list(STAGE_LABELS)
        # "render" is shown as part of "Assemble transcript".
        current = "merge" if job.stage == "render" else job.stage
        at = order.index(current) if job.state == "running" and current in order else None
        stages = []
        for i, key in enumerate(order):
            if job.state == "done" or (at is not None and i < at):
                state = "done"
            elif at is not None and i == at:
                state = "active"
            else:  # waiting, stopped, or failed: what finished earlier stays finished
                state = "done" if key in times else "todo"
            if key == "text" and state == "active" and n_chunks:
                note = f"{max(1, round(job.stage_fraction * n_chunks))} of {n_chunks} chunks"
            elif key in times and state == "done":
                secs = times[key]
                note = (
                    f"{secs:.1f} s"
                    if secs < 60
                    else f"{int(secs // 60)} min {int(secs % 60):02d} s"
                )
            else:
                note = ""
            stages.append({"label": STAGE_LABELS[key], "state": state, "note": note})
        row = _row(ctx, job, None)
        size = job.source.stat().st_size if job.source.exists() else None
        return {"job": job, "row": row, "stages": stages, "events": read_events(job_dir),
                "size": format.size(size) if size else None}  # fmt: skip

    @app.get("/jobs/<int:job_id>")
    def job_drawer(job_id: int):
        return render_template("_drawer.html", **_drawer_data(_ctx(), job_id))

    # ---- transcript editor ----------------------------------------------------------------
    @app.get("/jobs/<int:job_id>/edit")
    def editor(job_id: int):
        ctx = _ctx()
        try:
            job = ctx.store.get(job_id)
        except KeyError:
            abort(404)
        if job.state != "done":
            return redirect("/library")
        job_dir = ctx.scheduler.job_dir(job.id)
        try:
            t = read_current(job_dir)
        except (OSError, TranscriptError) as exc:
            log.warning("Can't open the transcript of job %s: %s", job.id, exc)
            return render_template(
                "editor_error.html",
                **_shell(ctx, "library"),
                job=job,
                title=format.title(job.name, job.source),
            )
        data = {
            "job": job.id,
            # Only the app window needs this check; a browser plays audio its own way.
            "audio_problem": window_audio_problem() if ctx.windowed else None,
            "duration": t.duration,
            "speakers": list(t.speakers),
            "names": dict(t.speaker_names),
            # [text, start, end] per word keeps the page small for long recordings.
            "turns": [
                {"speaker": turn.speaker, "words": [[w.text, w.start, w.end] for w in turn.words]}
                for turn in t.turns
            ],
        }
        stages = [st for st in _drawer_data(ctx, job.id)["stages"] if st["note"]]
        models = [t.engine[k] for k in ("text", "timings", "diarization") if k in t.engine]
        return render_template(
            "editor.html",
            **_shell(ctx, "library"),
            job=job,
            title=format.title(job.name, job.source),
            length=format.length(t.duration),
            n_speakers=len(t.speakers),
            language={"en": "English"}.get(t.language, t.language),
            device=format.device_label(job.device),
            models=models,
            finished=format.added(job.finished_at),
            stages=stages,
            exports=[(f, export.LABELS[f]) for f in export.available()],
            data=data,
        )

    _save_lock = threading.Lock()

    @app.post("/jobs/<int:job_id>/revision")
    def save_edits(job_id: int):
        """Autosave from the editor: check the edited transcript, save it, re-render outputs."""
        ctx = _ctx()
        try:
            job = ctx.store.get(job_id)
        except KeyError:
            abort(404)
        if job.state != "done":
            abort(409)
        request.max_content_length = 64 << 20  # long recordings make long transcripts
        job_dir = ctx.scheduler.job_dir(job.id)
        try:
            # force: the editor's last save on leaving is a beacon sent as text/plain.
            body = request.get_json(force=True, silent=True)
            edited = edited_transcript(body, read_artifact(job_dir))
        except TranscriptError as exc:
            log.warning("Refused an edit to job %s: %s", job.id, exc)
            return jsonify(error=str(exc)), 422
        with _save_lock:
            save_revision(job_dir, edited)
            write_outputs(job_dir, edited)
        ctx.store.update(job.id, speakers=len({t.speaker for t in edited.turns}))
        return jsonify(ok=True)

    @app.post("/jobs/<int:job_id>/rename")
    def rename(job_id: int):
        ctx = _ctx()
        job = _done_job(ctx, job_id)
        name = " ".join((request.form.get("name") or "").split())[:200]
        if not name:
            return jsonify(error="A recording needs a name."), 422
        ctx.store.update(job.id, name=name)
        return jsonify(name=name)

    @app.get("/jobs/<int:job_id>/original")
    def original(job_id: int):
        """The model's output, for "Restore original transcript" (an undoable edit)."""
        ctx = _ctx()
        t = read_artifact(ctx.scheduler.job_dir(_done_job(ctx, job_id).id))
        return jsonify(
            speakers=list(t.speakers),
            names={},
            turns=[
                {"speaker": turn.speaker, "words": [[w.text, w.start, w.end] for w in turn.words]}
                for turn in t.turns
            ],
        )

    def _export(ctx: AppContext, job: Job, fmt: str) -> tuple[bytes, str]:
        if fmt not in export.available():
            abort(404)
        t = read_current(ctx.scheduler.job_dir(job.id))
        title = format.title(job.name, job.source)
        return export.render(fmt, t, title), export.file_name(title, fmt)

    @app.get("/jobs/<int:job_id>/export/<fmt>")
    def export_download(job_id: int, fmt: str):
        """Export as a download, for the browser (the window saves through a dialog)."""
        ctx = _ctx()
        content, name = _export(ctx, _done_job(ctx, job_id), fmt)
        resp = make_response(content)
        resp.headers["Content-Type"] = "application/octet-stream"
        resp.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
        return resp

    @app.post("/jobs/<int:job_id>/export/<fmt>")
    def export_save(job_id: int, fmt: str):
        """Export in the window: ask where to save, write the file, remember the folder."""
        ctx = _ctx()
        if not ctx.native.save_file:
            abort(400)
        job = _done_job(ctx, job_id)
        content, name = _export(ctx, job, fmt)
        s = ctx.settings()
        folder = (
            s.export_dir if s.export_dir and Path(s.export_dir).is_dir() else str(job.source.parent)
        )
        chosen = ctx.native.save_file(name, folder)
        if not chosen:
            return jsonify(cancelled=True)
        path = Path(chosen)
        try:
            path.write_bytes(content)
        except OSError as exc:
            return jsonify(error=f"The file could not be saved: {exc.strerror or exc}."), 500
        ctx.save_settings(replace(ctx.settings(), export_dir=str(path.parent)))
        return jsonify(path=str(path))

    # ---- editor audio ---------------------------------------------------------------------
    def _done_job(ctx: AppContext, job_id: int) -> Job:
        try:
            job = ctx.store.get(job_id)
        except KeyError:
            abort(404)
        if job.state != "done":
            abort(404)
        return job

    @app.get("/jobs/<int:job_id>/audio/state")
    def audio_state(job_id: int):
        ctx = _ctx()
        job = _done_job(ctx, job_id)
        st = ctx.playback.ensure(job.id, job.source, ctx.scheduler.job_dir(job.id))
        return jsonify(state=st.state, message=st.message)

    @app.get("/jobs/<int:job_id>/audio")
    def audio(job_id: int):
        ctx = _ctx()
        path = ctx.scheduler.job_dir(_done_job(ctx, job_id).id) / PLAYBACK
        if not path.exists():
            abort(404)
        # conditional=True answers Range requests, which the web views use to seek.
        return send_file(path, mimetype="audio/ogg", conditional=True, max_age=0)

    @app.get("/jobs/<int:job_id>/body")
    def job_drawer_body(job_id: int):
        return render_template("_drawer_body.html", **_drawer_data(_ctx(), job_id))

    @app.post("/jobs/<int:job_id>/<action>")
    def job_action(job_id: int, action: str):
        ctx = _ctx()
        sched = ctx.scheduler
        if action == "stop":
            sched.stop(job_id)
        elif action in ("resume", "retry"):
            sched.resume(job_id)
        elif action == "delete":
            try:
                sched.remove(job_id)
            except RuntimeError:
                abort(409)
            resp = make_response("")
            resp.headers["HX-Trigger"] = json.dumps({"refresh": None, "close-drawer": None})
            return resp
        elif action == "open-folder":
            open_path(sched.job_dir(job_id) / "outputs")
        elif action == "open-log":
            open_path(sched.job_dir(job_id) / "worker.log")
        elif action in ("up", "down"):
            queued = [j for j in ctx.store.all() if j.state == "queued"]
            ids = [j.id for j in queued]
            if job_id in ids:
                i = ids.index(job_id)
                if action == "up" and i > 0:
                    sched.move(job_id, ids[i - 1])
                elif action == "down" and i + 1 < len(ids):
                    sched.move(job_id, ids[i + 2] if i + 2 < len(ids) else None)
        else:
            abort(404)
        resp = make_response("")
        resp.headers["HX-Trigger"] = "refresh"
        return resp

    # add recordings
    def _expand(paths: list[str]) -> list[Path]:
        out: list[Path] = []
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                out += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in MEDIA)
            elif p.is_file():
                out.append(p)
        seen, unique = set(), []
        for p in out:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return unique

    def _files_fragment(paths: list[Path]):
        from wavematerial.jobs.scheduler import _probe_duration

        files = [
            {"path": str(p), "name": p.name, "size": format.size(p.stat().st_size),
             "length": format.length(_probe_duration(p))}
            for p in paths
        ]  # fmt: skip
        return render_template("_add_files.html", files=files)

    @app.get("/add")
    def add_dialog():
        s = _ctx().settings()
        return render_template("_add.html", s=s, windowed=_ctx().windowed)

    @app.post("/add/files")
    def add_files():
        ctx = _ctx()
        current = request.form.getlist("paths")
        new: list[str] = []
        how = request.form.get("how")
        if how == "files" and ctx.native.pick_files:
            new = ctx.native.pick_files()
        elif how == "folder" and ctx.native.pick_folder:
            folder = ctx.native.pick_folder()
            new = [folder] if folder else []
        elif how in ("drop", "typed"):
            new = [p for p in json.loads(request.form.get("dropped", "[]")) if p]
        return _files_fragment(_expand(current + new))

    @app.post("/add")
    def add_submit():
        ctx = _ctx()
        paths = _expand(request.form.getlist("paths"))
        lo = int(request.form.get("min_speakers", 2))
        hi = int(request.form.get("max_speakers", 3))
        lo, hi = min(lo, hi), max(lo, hi)
        terms = [t.strip() for t in request.form.getlist("key_terms") if t.strip()]
        for p in paths:
            ctx.scheduler.add(p, min_speakers=lo, max_speakers=hi, key_terms=terms)
        if request.form.get("save_defaults"):
            ctx.save_settings(
                replace(ctx.settings(), min_speakers=lo, max_speakers=hi, key_terms=terms)
            )
        resp = make_response("")
        resp.headers["HX-Trigger"] = json.dumps({"refresh": None, "close-modal": None})
        return resp

    # settings
    def _models_data(ctx: AppContext) -> list[dict]:
        by_id = {m.id: m for m in ctx.manifest}
        rows = []
        for name, role, ids in SETTINGS_GROUPS:
            specs = [by_id[i] for i in ids]
            installed = all(is_installed(s, ctx.models_dir()) for s in specs)
            checked = [ctx_verify.results.get(s.id) for s in specs]
            if not installed:
                status = ("missing", "Missing")
            elif all(c == [] for c in checked):
                status = ("ok", "Verified")
            elif any(c for c in checked if c):
                status = ("bad", "Damaged")
            else:
                status = ("neutral", "Installed")
            rows.append({"name": name, "role": role, "status": status,
                         "size": format.size(sum(s.installed_size for s in specs))})  # fmt: skip
        return rows

    def _settings_data(ctx: AppContext) -> dict:
        s = ctx.settings()
        gpus = usable_gpus(ctx.devices, ctx.wsl)
        auto = choose(ctx.devices, replace(s, device="auto"), cores=ctx.cores, wsl=ctx.wsl,
                      unreliable=ctx.store.unreliable_gpus())  # fmt: skip
        auto_name = (
            f"{format.short_device(auto.description)} (Vulkan)"
            if auto.backend == "vulkan"
            else "the processor"
        )
        devices = [("auto", f"Automatic — {auto_name}")]
        devices += [
            (f"vulkan:{d.device_id}", f"{format.short_device(d.description)} (Vulkan)")
            for d in gpus
        ]
        devices.append(("cpu", "Processor only"))
        import psutil

        logical = psutil.cpu_count() or ctx.cores
        return {
            "s": s,
            "devices": devices,
            "threads_auto": max(1, ctx.cores - 1),
            "max_threads": logical,
            "models": _models_data(ctx),
            "models_dir": str(ctx.models_dir()),
            "verifying": ctx_verify.running,
            "moving": ctx_move.message,
            "unreliable": sorted(ctx.store.unreliable_gpus()),
            "update_msg": ctx.updates.message(),
            "update_available": ctx.updates.update_available(),
        }

    class _Verify:
        running = False
        results: dict[str, list[str]] = {}

    class _Move:
        message: str | None = None

    ctx_verify, ctx_move = _Verify(), _Move()

    @app.get("/settings")
    def settings_page():
        ctx = _ctx()
        return render_template("settings.html", **_shell(ctx, "settings"), **_settings_data(ctx))

    @app.post("/settings")
    def settings_save():
        ctx = _ctx()
        s = ctx.settings()
        f = request.form
        changes: dict = {}
        if "device" in f:
            changes["device"] = f["device"]
        if "threads" in f:
            changes["threads"] = int(f["threads"])
        if "min_speakers" in f and "max_speakers" in f:
            lo, hi = int(f["min_speakers"]), int(f["max_speakers"])
            changes["min_speakers"], changes["max_speakers"] = min(lo, hi), max(lo, hi)
        if f.get("key_terms_present"):
            changes["key_terms"] = [t.strip() for t in f.getlist("key_terms") if t.strip()]
        if "update_check" in f:  # a hidden "off" comes first, the checkbox adds "on"
            changes["update_check"] = f.getlist("update_check")[-1] == "on"
        ctx.save_settings(replace(s, **changes))
        resp = make_response("")
        resp.headers["HX-Trigger"] = "refresh"
        return resp

    @app.get("/settings/models")
    def settings_models():
        ctx = _ctx()
        return render_template("_models.html", **_settings_data(ctx))

    @app.post("/settings/verify")
    def settings_verify():
        ctx = _ctx()
        if not ctx_verify.running:
            ctx_verify.running = True

            def run():
                try:
                    for m in ctx.manifest:
                        ctx_verify.results[m.id] = verify(m, ctx.models_dir())
                finally:
                    ctx_verify.running = False

            threading.Thread(target=run, daemon=True).start()
        return render_template("_models.html", **_settings_data(ctx))

    @app.post("/settings/models-folder")
    def settings_models_folder():
        ctx = _ctx()
        if not ctx.native.pick_folder or ctx_move.message:
            return render_template("_models.html", **_settings_data(ctx))
        chosen = ctx.native.pick_folder()
        if chosen and Path(chosen) != ctx.models_dir():
            target, source = Path(chosen), ctx.models_dir()

            def move():
                try:
                    ctx_move.message = "Moving the models…"
                    target.mkdir(parents=True, exist_ok=True)
                    for m in ctx.manifest:
                        if m.folder(source).exists() and not m.folder(target).exists():
                            shutil.move(m.folder(source), m.folder(target))
                    ctx.save_settings(replace(ctx.settings(), models_dir=str(target)))
                    ctx_move.message = None
                except OSError as exc:
                    log.exception("Moving the models failed")
                    ctx_move.message = f"Could not move the models: {exc}"

            threading.Thread(target=move, daemon=True).start()
        return render_template("_models.html", **_settings_data(ctx))

    @app.post("/settings/reset-gpu")
    def settings_reset_gpu():
        _ctx().store.reset_unreliable_gpus()
        resp = make_response("")
        resp.headers["HX-Refresh"] = "true"
        return resp

    @app.post("/updates/check")
    def updates_check():
        ctx = _ctx()
        ctx.updates.check_in_background(force=True)
        return render_template("_updates.html", **_settings_data(ctx))

    @app.get("/updates/status")
    def updates_status():
        return render_template("_updates.html", **_settings_data(_ctx()))

    @app.post("/open/<what>")
    def open_thing(what: str):
        ctx = _ctx()
        if what == "data":
            open_path(ctx.paths.data_dir)
        elif what == "logs":
            ctx.paths.logs_dir.mkdir(parents=True, exist_ok=True)
            open_path(ctx.paths.logs_dir)
        elif what == "releases":
            webbrowser.open(ctx.updates.status.url or RELEASES_PAGE)
        else:
            abort(404)
        return ("", 204)

    @app.post("/fullscreen")
    def fullscreen():
        ctx = _ctx()
        if ctx.native.toggle_fullscreen:
            ctx.fullscreen = ctx.native.toggle_fullscreen()
        return render_template("_f11.html", full=ctx.fullscreen)

    # licences and credits
    @app.get("/credits")
    def credits_page():
        ctx = _ctx()
        return render_template(
            "credits.html", **_shell(ctx, "settings"), models=ctx.manifest,
            software=credits.software(), bundled=credits.BUNDLED,
        )  # fmt: skip

    @app.get("/credits/licence/<path:name>")
    def credits_licence(name: str):
        text = credits.licence_text(name)
        if text is None:
            abort(404)
        return render_template("_licence.html", name=name, text=text)

    @app.errorhandler(404)
    def not_found(_):
        return render_template("_message.html", message="That item no longer exists."), 404

    @app.errorhandler(409)
    def conflict(_):
        return render_template("_message.html", message="Stop the job first."), 409
