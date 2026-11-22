# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""The Playwright half of make.py: the USAGE screenshots and the README video."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from make import (
    AUDIO,
    CHROMIUM,
    KEY_TERM,
    OUT_VIDEO,
    SHOTS_DIR,
    SPEAKERS,
    WORK,
    Server,
    fetch_audio,
    log,
    make_home,
)
from PIL import Image
from playwright.sync_api import Page, sync_playwright

VIEW = {"width": 1920, "height": 1080}
# A dot that follows the mouse: recordings don't show the pointer.
CURSOR = """
addEventListener("DOMContentLoaded", () => {
  const dot = document.createElement("div");
  dot.style.cssText = "position:fixed;z-index:2147483647;pointer-events:none;width:18px;" +
    "height:18px;margin:-9px 0 0 -9px;border-radius:50%;background:rgba(255,255,255,.85);" +
    "box-shadow:0 0 0 2px rgba(0,0,0,.55);transition:transform .08s;left:-40px;top:-40px";
  document.body.appendChild(dot);
  addEventListener("mousemove", (e) => {
    dot.style.left = e.clientX + "px";
    dot.style.top = e.clientY + "px";
  }, true);
  addEventListener("mousedown", () => { dot.style.transform = "scale(.7)"; }, true);
  addEventListener("mouseup", () => { dot.style.transform = ""; }, true);
});
"""


# What the page's <audio> plays, and when (wall clock), so the soundtrack can be rebuilt
# afterwards: recordings have no sound.
AUDIO_LOG = """
window.__wmAudio = [];
for (const type of ["playing", "pause", "ended", "seeking"]) {
  addEventListener(type, (e) => {
    if (e.target instanceof HTMLMediaElement) {
      window.__wmAudio.push({type, t: Date.now() / 1000, pos: e.target.currentTime,
                             rate: e.target.playbackRate});
    }
  }, true);
}
"""


def use_system_ffmpeg() -> None:
    """Playwright records video with its own ffmpeg build; point it at the system's instead
    (a private browsers folder holding just a link where it looks for ffmpeg)."""
    import playwright

    listing = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
    revision = next(b["revision"] for b in json.loads(listing.read_text()) ["browsers"]
                    if b["name"] == "ffmpeg")  # fmt: skip
    folder = WORK / "playwright"
    link = folder / f"ffmpeg-{revision}" / "ffmpeg-linux"
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.exists():
        link.symlink_to(shutil.which("ffmpeg"))
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(folder)


def browser(p, video_dir: Path | None = None):
    b = p.chromium.launch(
        executable_path=CHROMIUM, args=["--autoplay-policy=no-user-gesture-required"]
    )
    ctx = b.new_context(
        viewport=VIEW, device_scale_factor=1, bypass_csp=True,
        record_video_dir=str(video_dir) if video_dir else None, record_video_size=VIEW,
    )  # fmt: skip
    if video_dir:
        ctx.add_init_script(CURSOR)
        ctx.add_init_script(AUDIO_LOG)
    return b, ctx


def save(page: Page, name: str, clip: dict | None = None) -> None:
    """A screenshot into demo/usage/, tagged 300 ppi like the others."""
    tmp = SHOTS_DIR / f".{name}"
    page.screenshot(path=str(tmp), clip=clip)
    Image.open(tmp).convert("RGB").save(SHOTS_DIR / name, dpi=(300, 300), optimize=True)
    tmp.unlink()
    log(f"saved demo/usage/{name}")


def glide(page: Page, target, steps: int = 25, pause: float = 0.25) -> None:
    """Move the mouse smoothly to the middle of `target` (a selector or a locator)."""
    loc = page.locator(target).first if isinstance(target, str) else target
    box = loc.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=steps)
    time.sleep(pause)


def click(page: Page, target, pause: float = 0.5) -> None:
    glide(page, target)
    page.mouse.down()
    page.mouse.up()
    time.sleep(pause)


def add_recordings(page: Page, slow: bool = False) -> None:
    """Landing → Add recordings → the demo recording, its speaker range and key term → Add."""
    step = click if slow else (lambda pg, t, pause=0.2: pg.locator(t).first.click())
    step(page, "text=Add recordings…")
    page.wait_for_selector("#add-form")
    step(page, "text=Choose files…")
    page.wait_for_selector("#add-files .file-row", timeout=10000)
    page.select_option("select[name=min_speakers]", SPEAKERS[0])
    page.select_option("select[name=max_speakers]", SPEAKERS[1])
    terms = page.locator("#add-form .tags input").first
    if slow:
        glide(page, terms)
    terms.click()
    terms.type(KEY_TERM, delay=110 if slow else 0)
    terms.press("Enter")
    step(page, "#add-submit")


def wait_until(page: Page, test, timeout: float, every: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if test():
            return
        time.sleep(every)
    raise TimeoutError("waited too long")


def jobs_done(page: Page, server: Server, n: int) -> bool:
    """Whether `n` recordings show as done (asked with the page's own cookies)."""
    html = page.request.get(f"http://127.0.0.1:{server.port}/library").text()
    return html.count("pill-done") >= n


class UpdateStandIn:
    """A local stand-in for the release page that offers version `latest`."""

    def __init__(self, folder: Path, latest: str):
        (folder / "releases").mkdir(parents=True, exist_ok=True)
        handler = partial(SimpleHTTPRequestHandler, directory=str(folder))
        handler.log_message = lambda *a: None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        release = {"tag_name": f"v{latest}", "html_url": self.base, "assets": []}
        (folder / "releases" / "latest").write_text(json.dumps(release), encoding="utf-8")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()


def next_patch() -> str:
    """The app's version with the patch number raised: what the stand-in offers."""
    init = (
        Path(__file__).resolve().parents[2] / "src" / "wavematerial" / "__init__.py"
    ).read_text()
    major, minor, patch = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', init).groups()
    return f"{major}.{minor}.{int(patch) + 1}"


# A second minute of the same scene (4:00-5:00), so the library has two recordings.
SECOND = ("The Seagull - Act I, later excerpt.mp3", 240, 60)


def second_recording(home: Path) -> None:
    out = home / "Recordings" / SECOND[0]
    if not out.exists():
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", str(SECOND[1]), "-t", str(SECOND[2]), "-i",
             str(fetch_audio()[0]), "-c", "copy", str(out)], check=True,
        )  # fmt: skip


def screenshots() -> int:
    """Every screenshot in USAGE.md, in the order of the tour."""
    with sync_playwright() as p:
        b, ctx = browser(p)
        page = ctx.new_page()

        log("01: the first-run screen (no models in this sandbox)")
        first = Server(make_home("first-run"), models=False)
        try:
            page.goto(first.url("/setup"))
            page.wait_for_selector("text=Download models")
            save(page, "01-first-run-setup.png")
        finally:
            first.stop()

        home = make_home("shots")
        second_recording(home)
        main = Server(home)
        try:
            log("02: the landing screen")
            page.goto(main.url("/"))
            page.wait_for_selector("text=Add recordings…")
            time.sleep(0.5)
            save(page, "02-landing.png")

            log("03: the Add recordings dialog")
            page.locator("text=Add recordings…").first.click()
            page.wait_for_selector("#add-form")
            page.locator("text=Choose files…").first.click()
            page.wait_for_selector("#add-files .file-row >> nth=1", timeout=10000)
            page.select_option("select[name=min_speakers]", SPEAKERS[0])
            page.select_option("select[name=max_speakers]", SPEAKERS[1])
            terms = page.locator("#add-form .tags input").first
            terms.click()
            terms.type(KEY_TERM)
            terms.press("Enter")
            page.locator("#add-submit").focus()
            time.sleep(0.4)
            save(page, "03-add-recordings.png")

            log("29: added to the library, not started")
            page.locator("#add-later").click()
            page.wait_for_url("**/library**")  # adding from the landing screen goes there
            page.wait_for_selector("#start-all", timeout=10000)
            time.sleep(0.6)
            save(page, "29-library-not-started.png")

            log("04: one transcribing, one waiting")
            page.locator("#start-all").click()
            page.wait_for_selector("text=Transcribing", timeout=60000)
            page.wait_for_selector(".pill-queued", timeout=10000)
            time.sleep(2.5)
            save(page, "04-library-transcribing.png")

            log("05: a recording's details while it is transcribed")
            running = page.locator(".job-row.is-running")
            running.locator(".row-open").click()
            page.wait_for_selector("[data-copy-report]")
            time.sleep(1)
            save(page, "05-job-details.png")
            wait_until(page, lambda: jobs_done(page, main, 2), timeout=1200)

            log("06: the library with both finished")
            page.goto(main.url("/library"))
            page.wait_for_selector("text=Edit transcript")
            time.sleep(0.6)
            save(page, "06-library.png")

            log("30: a finished recording's details")
            first_row = page.locator(".job-row").filter(has_text="Act I, excerpt")
            first_row.locator("summary").click()
            first_row.get_by_role("button", name="Details").click()
            page.wait_for_selector(".drawer-main")
            time.sleep(0.8)
            save(page, "30-job-details-finished.png")
            page.goto(main.url("/library"))

            log("07: searching the transcripts")
            search = page.locator("#library-filters input[type=search]")
            search.click()
            search.type("sultry", delay=40)
            time.sleep(1.5)
            save(page, "07-library-search.png")
            page.goto(main.url("/library"))

            log("08: a row's menu")
            row = page.locator(".job-row").filter(has_text="Act I, excerpt")
            row.locator("summary").click()
            time.sleep(0.4)
            save(page, "08-library-row-menu.png")

            log("09: Transcribe again")
            row.get_by_role("button", name="Transcribe again…").click()
            page.wait_for_selector("#modal .modal-card", timeout=10000)
            time.sleep(0.6)
            save(page, "09-transcribe-again.png")
            page.goto(main.url("/library"))

            log("10: searching from the sidebar")
            side = page.locator(".nav-search input")
            side.click()
            side.type("Sorin", delay=40)
            time.sleep(1.5)
            save(page, "10-sidebar-search.png")
            page.goto(main.url("/library"))

            log("11: the editor")
            row = page.locator(".job-row").filter(has_text="Act I, excerpt")
            row.get_by_role("link", name="Edit the transcript", exact=False).click()
            page.wait_for_selector("#turns .turn")
            if page.locator("#sel-tip-close").is_visible():
                page.locator("#sel-tip-close").click()
            time.sleep(1.2)
            save(page, "11-editor.png")

            log("12: playing with Follow")
            page.locator("#play").click()
            time.sleep(3.2)
            save(page, "12-editor-playing-follow.png")
            page.locator("#play").click()
            time.sleep(0.4)

            log("13: a selection")
            drag_words(
                page, word(page, "The", "air is sultry"), word(page, "tonight.", "air is sultry")
            )
            page.wait_for_selector("#sel-pop:not([hidden])")
            time.sleep(0.6)
            save(page, "13-editor-selection.png")
            page.keyboard.press("Escape")
            time.sleep(0.3)

            log("14: a turn's speaker menu")
            sorin = page.locator(".turn").filter(has_text="country life").first
            sorin.scroll_into_view_if_needed()
            sorin.locator(".turn-speaker").click()
            page.wait_for_selector("#spk-menu:not([hidden])")
            time.sleep(0.5)
            save(page, "14-editor-speaker-menu.png")

            log("15: the speakers named")
            page.locator("#spk-menu .menu-item", has_text="New speaker").click()
            time.sleep(0.5)
            for n, name in enumerate(("Masha", "Medviedenko", "Stage directions", "Sorin")):
                box = page.locator(f'.spk-input[data-speaker="SPEAKER_0{n}"]')
                box.click()
                box.fill(name)
                page.keyboard.press("Enter")
                time.sleep(0.3)
            page.mouse.click(5, 1070)  # away from the inputs
            time.sleep(0.8)
            save(page, "15-editor-speakers-named.png")

            log("16: Merge into…")
            page.locator('.spk-merge[data-merge="SPEAKER_03"]').click()
            page.wait_for_selector("#spk-menu:not([hidden])")
            time.sleep(0.5)
            save(page, "16-editor-merge-into.png")
            page.keyboard.press("Escape")
            time.sleep(0.3)

            log("17: find and replace")
            page.locator("#find").click()
            page.locator("#find").type("Treplief", delay=40)
            page.locator("#find-toggle").click()
            page.locator("#find-replace").fill("Treplieff")
            time.sleep(0.8)
            save(page, "17-editor-find-replace.png")
            page.locator("#replace-all").click()
            time.sleep(0.6)
            page.locator("#find").fill("")
            page.locator("#find-toggle").click()
            page.mouse.click(5, 1070)

            log("18: the right-click menu")
            w = word(page, "storm", "air is sultry")
            w.scroll_into_view_if_needed()
            w.click(button="right")
            page.wait_for_selector("#ctx-menu:not([hidden])")
            time.sleep(0.5)
            save(page, "18-editor-context-menu.png")
            page.keyboard.press("Escape")
            time.sleep(0.3)

            log("19: transcribing a passage again")
            drag_words(
                page, word(page, "You", "air is sultry"), word(page, "moralise,", "air is sultry")
            )
            page.wait_for_selector("#sel-pop:not([hidden])")
            box = word(page, "nothing", "air is sultry").bounding_box()
            page.mouse.click(box["x"] + 3, box["y"] + 5, button="right")
            item = page.locator("#ctx-menu .menu-item", has_text="Transcribe again")
            wait_until(page, lambda: item.is_enabled(), 30, 1.0)
            item.click()
            page.wait_for_selector("#passage-result:not([hidden])", timeout=180000)
            time.sleep(0.6)
            save(page, "19-editor-transcribe-passage.png")
            page.locator("#passage-cancel").click()
            time.sleep(0.4)
            page.keyboard.press("Escape")

            log("20: History")
            page.locator("#tab-btn-history").click()
            page.locator("#save-version").click()
            page.locator("#version-name").fill("First pass")
            page.keyboard.press("Enter")
            time.sleep(1.0)
            save(page, "20-editor-history.png")

            log("21: Details")
            page.locator("#tab-btn-details").click()
            time.sleep(0.6)
            save(page, "21-editor-details.png")
            page.locator("#tab-btn-speakers").click()

            log("22: the Export menu")
            page.locator("#export-menu summary").click()
            time.sleep(0.5)
            save(page, "22-editor-export-menu.png")
            page.locator("#export-menu summary").click()

            log("23: renaming")
            page.locator("#rename-btn").click()
            time.sleep(0.5)
            save(page, "23-editor-rename.png")
            page.keyboard.press("Escape")
            time.sleep(0.3)

            log("24: the editor's ⋯ menu")
            page.locator("#more-menu summary").click()
            time.sleep(0.5)
            save(page, "24-editor-more-menu.png")
            page.locator("#more-menu summary").click()

            log("25 and 26: Settings")
            page.goto(main.url("/settings"))
            time.sleep(0.8)
            save(page, "25-settings.png")
            page.mouse.wheel(0, 4000)
            time.sleep(0.6)
            save(page, "26-settings-lower.png")

            log("27: Licences and credits")
            page.goto(main.url("/credits"))
            time.sleep(0.8)
            save(page, "27-credits.png")
        finally:
            main.stop()

        newer = next_patch()
        log(f"28: an update is available (a local stand-in offers {newer})")
        stand_in = UpdateStandIn(WORK / "update-stand-in", newer)
        upd = Server(home, env={"WAVEMATERIAL_UPDATE_SERVER": stand_in.base}, pretend="tarball")
        try:
            page.goto(upd.url("/settings"))
            self_update = page.get_by_role("button", name="Self-update", exact=True)

            def offered() -> bool:
                if self_update.count():
                    return True
                page.reload()  # the check may finish after the page loaded
                return False

            wait_until(page, offered, 30, 2.0)
            page.evaluate("document.getElementById('updates').scrollIntoView({block: 'center'})")
            self_update.focus()
            page.keyboard.press("Tab")
            time.sleep(0.4)
            save(page, "28-settings-update.png")
        finally:
            upd.stop()
            stand_in.stop()
        b.close()
    return 0


class Segment:
    """One recorded browser context; `ready()` marks where the usable footage starts."""

    def __init__(self, p, folder: Path):
        self.b, self.ctx = browser(p, folder)
        self.page = self.ctx.new_page()
        self.created = time.monotonic()
        self.created_wall = time.time()
        self.start = 0.0

    def ready(self) -> None:
        self.start = time.monotonic() - self.created

    def played(self) -> list[tuple[float, float, float, float]]:
        """(video time, audio position, length, rate) of each stretch the page played."""
        events = self.page.evaluate("window.__wmAudio || []")
        out, open_ = [], None
        for e in events:
            if open_ and e["type"] in ("pause", "ended", "seeking"):
                t0, pos, rate = open_
                if e["t"] > t0:
                    out.append((t0 - self.created_wall - self.start, pos, e["t"] - t0, rate))
                open_ = None
            if e["type"] == "playing":
                open_ = (e["t"], e["pos"], e["rate"])
        return out

    def close(self) -> tuple[Path, float]:
        video = self.page.video
        self.ctx.close()
        self.b.close()
        return Path(video.path()), self.start


def word(page: Page, text: str, turn_has: str):
    """A word in the transcript, found by its text within a turn containing `turn_has`."""
    turn = page.locator(".turn").filter(has_text=turn_has).first
    return turn.locator("span.w", has_text=text).first


def drag_words(page: Page, first, last) -> None:
    a, z = first.bounding_box(), last.bounding_box()
    page.mouse.move(a["x"] + 2, a["y"] + a["height"] / 2, steps=20)
    time.sleep(0.2)
    page.mouse.down()
    page.mouse.move(z["x"] + z["width"] - 2, z["y"] + z["height"] / 2, steps=25)
    page.mouse.up()


def type_slow(page: Page, text: str, delay: int = 75) -> None:
    page.keyboard.type(text, delay=delay)


def video() -> int:
    """The README video: first run, adding recordings, then the editor (about 60 s)."""
    use_system_ffmpeg()
    folder = WORK / "video-segments"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    parts: list[tuple[Path, float]] = []
    with sync_playwright() as p:
        log("segment 1: the first-run screen")
        first = Server(make_home("video-first-run"), models=False)
        seg = Segment(p, folder)
        try:
            seg.page.goto(first.url("/setup"))
            seg.page.wait_for_selector("text=Download models")
            seg.ready()
            time.sleep(1.2)
            glide(seg.page, "text=Download models", steps=35, pause=1.8)
        finally:
            parts.append(seg.close())
            first.stop()

        log("segment 2, one take: adding the recording, transcribing, the editor")
        main = Server(make_home("video"))
        try:
            seg = Segment(p, folder)
            page = seg.page
            page.goto(main.url("/"))
            page.wait_for_selector("text=Add recordings…")
            seg.ready()
            time.sleep(1.0)
            add_recordings(page, slow=True)
            page.wait_for_selector("text=Transcribing", timeout=60000)
            glide(page, ".job-row .status", steps=30, pause=0.5)
            wait_until(page, lambda: page.locator(".pill-done").count() > 0, 1200, 0.5)
            time.sleep(1.5)
            row = page.locator(".job-row").filter(has_text="Act I")
            click(page, row.get_by_role("link", name="Edit the transcript", exact=False))
            page.wait_for_selector("#turns .turn")
            time.sleep(1.5)

            click(page, "#play", pause=5.0)  # plays with Follow on
            click(page, "#play", pause=0.6)

            first, last = word(page, "The", "air is sultry"), word(page, "sultry.", "air is sultry")
            drag_words(page, first, last)
            page.wait_for_selector("#sel-pop:not([hidden])")
            time.sleep(0.6)
            click(page, "#sel-play", pause=2.2)
            page.keyboard.press("Escape")
            time.sleep(0.4)

            # The speakers, named from the LibriVox cast.
            for n, name in enumerate(("Masha", "Medviedenko", "Stage directions")):
                click(page, f'.spk-input[data-speaker="SPEAKER_0{n}"]', pause=0.2)
                type_slow(page, name)
                page.keyboard.press("Enter")
                time.sleep(0.35)

            # Sorin's speech was put with Medviedenko (two men's voices): give it its own.
            sorin = page.locator(".turn").filter(has_text="country life").first
            sorin.scroll_into_view_if_needed()
            click(page, sorin.locator(".turn-speaker"), pause=0.5)
            click(page, page.locator("#spk-menu .menu-item", has_text="New speaker"), pause=0.6)
            click(page, '.spk-input[data-speaker="SPEAKER_03"]', pause=0.2)
            type_slow(page, "Sorin")
            page.keyboard.press("Enter")
            time.sleep(0.6)

            # This translation spells it "Treplieff".
            click(page, "#find", pause=0.2)
            type_slow(page, "Treplief", 110)
            time.sleep(0.8)
            click(page, "#find-toggle", pause=0.3)
            click(page, "#find-replace", pause=0.2)
            type_slow(page, "Treplieff", 110)
            click(page, "#replace-all", pause=1.3)

            click(page, "#tab-btn-history", pause=0.5)
            click(page, "#save-version", pause=0.3)
            type_slow(page, "First pass")
            page.keyboard.press("Enter")
            time.sleep(1.5)

            click(page, "#export-menu summary", pause=0.8)
            click(page, '[data-export="docx"]', pause=2.4)
            played = seg.played()
            parts.append(seg.close())
        finally:
            main.stop()
    audio = WORK / "video" / "Recordings" / AUDIO[0][2]
    encode(parts, OUT_VIDEO, sound=(audio, played))
    return 0


def duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip())  # fmt: skip


TRIM = 0.3  # cut from each segment's start, past the page appearing


def encode(parts: list[tuple[Path, float]], out: Path, sound=None) -> None:
    """Trim each segment's start, join them, and encode VP9. `sound` is (audio file, the last
    segment's played stretches): the soundtrack is that audio where the page played it, and
    silence elsewhere (Opus)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for path, start in parts:
        cmd += ["-ss", f"{start + TRIM:.2f}", "-i", str(path)]
    joined = "".join(f"[{i}:v]" for i in range(len(parts)))
    graph = f"{joined}concat=n={len(parts)}:v=1:a=0,fps=25[v]"
    maps = ["-map", "[v]"]
    if sound and sound[1]:
        audio, played = sound
        before = sum(duration(path) - start - TRIM for path, start in parts[:-1])
        cmd += ["-i", str(audio)]
        a = len(parts)
        clips = []
        for i, (at, pos, length, rate) in enumerate(played):
            delay = max(0, round((before + at - TRIM) * 1000))
            tempo = f",atempo={rate}" if abs(rate - 1) > 0.01 else ""
            graph += (
                f";[{a}:a]atrim=start={pos:.3f}:duration={length * rate:.3f},"
                f"asetpts=PTS-STARTPTS{tempo},adelay={delay}:all=1[a{i}]"
            )
            clips.append(f"[a{i}]")
        graph += f";{''.join(clips)}amix=inputs={len(clips)}:normalize=0,apad[a]"
        maps += ["-map", "[a]", "-c:a", "libopus", "-b:a", "64k", "-shortest"]
    else:
        maps += ["-an"]
    cmd += ["-filter_complex", graph, *maps, "-c:v", "libvpx-vp9", "-crf", "33",
            "-b:v", "0", "-row-mt", "1", str(out)]  # fmt: skip
    subprocess.run(cmd, check=True)
    log(f"video: {out} ({duration(out):.0f} s, {out.stat().st_size / 1e6:.1f} MB)")
