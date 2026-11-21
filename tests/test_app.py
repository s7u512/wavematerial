# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Starting the app window."""

import sys
import types

import pytest

from wavematerial import app


def test_windows_without_webview2_takes_the_browser_not_internet_explorer(monkeypatch):
    # pywebview quietly falls back to MSHTML when WebView2 is missing; the app must refuse it
    # (main() then opens the browser) before any window is created.
    import webview
    import webview.platforms

    fake = types.ModuleType("webview.platforms.winforms")
    fake.renderer = "mshtml"
    monkeypatch.setitem(sys.modules, "webview.platforms.winforms", fake)
    monkeypatch.setattr(webview.platforms, "winforms", fake, raising=False)
    monkeypatch.setattr(app.sys, "platform", "win32")
    created = []
    monkeypatch.setattr(webview, "create_window", lambda *a, **k: created.append(a))
    with pytest.raises(RuntimeError, match="WebView2"):
        app._open_window(None, "http://127.0.0.1:1/")
    assert not created


def test_browser_mode_quits_on_request_or_once_no_page_is_open():
    import threading
    import time

    from wavematerial.web.context import AppContext

    ctx = AppContext.__new__(AppContext)  # only the browser-mode fields are used here
    ctx.quit = threading.Event()
    ctx.last_seen = 0.0
    threading.Timer(0.05, ctx.quit.set).start()
    assert app._serve_browser(ctx, idle_exit=60, tick=0.01) == "quit"

    ctx.quit = threading.Event()
    stop = time.monotonic() + 0.3

    def page_open():  # a page checks in for 0.3 s, then the tab is closed
        while time.monotonic() < stop:
            ctx.last_seen = time.monotonic()
            time.sleep(0.01)

    threading.Thread(target=page_open, daemon=True).start()
    started = time.monotonic()
    assert app._serve_browser(ctx, idle_exit=0.2, tick=0.01) == "idle"
    assert time.monotonic() - started >= 0.45  # not while the page was open
