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

from make import CHROMIUM, KEY_TERM, OUT_VIDEO, SHOTS_DIR, SPEAKERS, WORK, Server, log, make_home
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


def screenshots() -> int:
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

        log("03: the Add recordings dialog")
        home = make_home("shots")
        main = Server(home)
        try:
            page.goto(main.url("/"))
            page.locator("text=Add recordings…").first.click()
            page.wait_for_selector("#add-form")
            page.locator("text=Choose files…").first.click()
            page.wait_for_selector("#add-files .file-row", timeout=10000)
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

            log("05: a recording's details while it is transcribed")
            row = page.locator(".job-row").filter(has_text="Act I")
            row.get_by_role("button", name="Start", exact=False).first.click()
            page.wait_for_selector("text=Transcribing", timeout=60000)
            time.sleep(2)  # into the first stages (a minute of audio is quick)
            row.locator(".row-open").click()
            page.wait_for_selector("[data-copy-report]")
            time.sleep(1)
            save(page, "05-job-details.png")
            wait_until(page, lambda: jobs_done(page, main, 1), timeout=1200)

            log("06 and 08: the library with the finished recording, and its row menu")
            page.goto(main.url("/library"))
            page.wait_for_selector("text=Edit transcript")
            time.sleep(0.6)
            save(page, "06-library.png")
            page.locator(".job-row").first.locator("summary").click()
            time.sleep(0.4)
            save(page, "08-library-row-menu.png")

            log("26: Settings, lower part")
            page.goto(main.url("/settings"))
            page.mouse.wheel(0, 4000)
            time.sleep(0.6)
            save(page, "26-settings-lower.png")
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


CAPTION = """(text) => {
  const c = document.createElement("div");
  c.id = "demo-caption";
  c.textContent = text;
  c.style.cssText = "position:fixed;z-index:2147483646;left:50%;top:22px;" +
    "transform:translateX(-50%);" +
    "padding:10px 18px;border-radius:10px;background:rgba(20,22,26,.92);color:#fff;" +
    "font:600 16px Inter,system-ui,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.5)";
  document.body.appendChild(c);
}"""


class Segment:
    """One recorded browser context; `ready()` marks where the usable footage starts."""

    def __init__(self, p, folder: Path):
        self.b, self.ctx = browser(p, folder)
        self.page = self.ctx.new_page()
        self.created = time.monotonic()
        self.start = 0.0

    def ready(self) -> None:
        self.start = time.monotonic() - self.created

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

        log("segment 2: adding the recordings")
        main = Server(make_home("video"))
        try:
            seg = Segment(p, folder)
            page = seg.page
            page.goto(main.url("/"))
            page.wait_for_selector("text=Add recordings…")
            seg.ready()
            time.sleep(1.0)
            add_recordings(page, slow=True)
            submitted = time.monotonic()
            page.wait_for_selector("text=Transcribing", timeout=60000)
            time.sleep(3.5)
            parts.append(seg.close())

            log("waiting for the transcriptions (not recorded)")
            watcher = Segment(p, folder)  # a throwaway context to poll with
            watcher.page.goto(main.url("/library"))
            wait_until(watcher.page, lambda: jobs_done(watcher.page, main, 1), 1200, 1.0)
            took = time.monotonic() - submitted
            watcher.close()[0].unlink(missing_ok=True)
            caption = f"Transcribing this minute took {round(took)} s · skipped ahead"
            log(caption)

            log("segment 3: the editor")
            seg = Segment(p, folder)
            page = seg.page
            page.goto(main.url("/library"))
            page.wait_for_selector(".pill-done")
            page.evaluate(CAPTION, caption)
            seg.ready()
            time.sleep(2.6)
            page.evaluate("document.getElementById('demo-caption').remove()")
            click(page, page.locator(".job-row").filter(has_text="Act I").locator(".row-open"))
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
            parts.append(seg.close())
        finally:
            main.stop()
    encode(parts, OUT_VIDEO)
    return 0


def encode(parts: list[tuple[Path, float]], out: Path) -> None:
    """Trim each segment's start, join them, and encode VP9 (no sound)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for path, start in parts:
        cmd += ["-ss", f"{start + 0.3:.2f}", "-i", str(path)]
    joined = "".join(f"[{i}:v]" for i in range(len(parts)))
    graph = f"{joined}concat=n={len(parts)}:v=1:a=0,fps=25[v]"
    cmd += ["-filter_complex", graph, "-map", "[v]", "-c:v", "libvpx-vp9", "-crf", "33",
            "-b:v", "0", "-row-mt", "1", "-an", str(out)]  # fmt: skip
    subprocess.run(cmd, check=True)
    length = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    log(f"video: {out} ({float(length):.0f} s, {out.stat().st_size / 1e6:.1f} MB)")
