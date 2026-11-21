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
