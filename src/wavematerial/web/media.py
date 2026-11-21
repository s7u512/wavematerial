# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Whether the app window can play audio.

On Linux the window is WebKitGTK, which plays media through the system's GStreamer. If
GStreamer's `autoaudiosink` element (from its "good" plugin set) is missing, WebKitGTK's
page process crashes as soon as an audio element loads, taking the whole window with it.
So the editor asks first, and without that element it doesn't load audio at all.
"""

from __future__ import annotations

import functools
import logging
import sys

log = logging.getLogger(__name__)

MISSING_SINK = (
    "Playback needs GStreamer's “good” plugins (the gst-plugins-good or "
    "gstreamer1.0-plugins-good package). Install them and restart WaveMaterial to listen "
    "while you edit."
)


@functools.cache
def window_audio_problem() -> str | None:
    """Why the window can't play audio, or None if it can (or there's no way to tell)."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        Gst.init(None)
    except (ImportError, ValueError) as exc:  # no GStreamer bindings: let WebKit try
        log.info("Can't check GStreamer for audio playback: %s", exc)
        return None
    if Gst.ElementFactory.find("autoaudiosink") is None:
        log.warning("GStreamer has no autoaudiosink; audio playback is turned off")
        return MISSING_SINK
    return None
