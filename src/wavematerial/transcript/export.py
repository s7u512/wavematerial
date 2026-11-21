# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Export: a transcript as a file the user saves. docx and pdf are made only on export.

Formatting stays as plain as the other outputs: a title, then `SPEAKER: text` per turn.
docx needs python-docx and pdf needs reportlab, both in the optional `export` extra; a
format whose library is missing is simply not offered.
"""

from __future__ import annotations

import importlib.util
import io
import re
from pathlib import Path
from xml.sax.saxutils import escape

from wavematerial.transcript.render import render_json, render_srt, render_txt, render_vtt
from wavematerial.transcript.schema import Transcript

LABELS = {
    "txt": "Plain text (.txt)",
    "srt": "Subtitles (.srt)",
    "vtt": "Web subtitles (.vtt)",
    "json": "Data with word timings (.json)",
    "docx": "Document (.docx)",
    "pdf": "PDF (.pdf)",
}
_NEEDS = {"docx": "docx", "pdf": "reportlab"}
_TEXT = {"txt": render_txt, "srt": render_srt, "vtt": render_vtt, "json": render_json}
FONTS = Path(__file__).parent / "fonts"


def available() -> list[str]:
    """The formats this installation can export, in menu order."""
    return [f for f in LABELS if f not in _NEEDS or importlib.util.find_spec(_NEEDS[f])]


# Names Windows reserves for devices, with or without an extension.
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{d}{n}" for d in ("COM", "LPT") for n in range(1, 10)}


def file_name(title: str, fmt: str) -> str:
    """A safe default file name: the recording's title, without characters files can't have.

    It must work on Windows too: no reserved device names, and no trailing dots or spaces.
    """
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", title)[:150].strip(" .") or "transcript"
    if safe.split(".")[0].upper() in _RESERVED:
        safe = f"_{safe}"
    return f"{safe}.{fmt}"


def render(fmt: str, t: Transcript, title: str) -> bytes:
    if fmt in _TEXT:
        return _TEXT[fmt](t).encode("utf-8")
    if fmt == "docx":
        return _docx(t, title)
    if fmt == "pdf":
        return _pdf(t, title)
    raise ValueError(f"unknown export format {fmt!r}")


def _docx(t: Transcript, title: str) -> bytes:
    from docx import Document

    doc = Document()
    doc.core_properties.title = title
    doc.add_heading(title, level=1)
    for turn in t.turns:
        p = doc.add_paragraph()
        p.add_run(f"{t.display_name(turn.speaker)}: ").bold = True
        p.add_run(turn.text)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _pdf(t: Transcript, title: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    # Noto Sans covers Latin with diacritics, Greek, and Cyrillic, unlike PDF's base fonts.
    if "NotoSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("NotoSans", FONTS / "NotoSans-Regular.ttf"))
        pdfmetrics.registerFont(TTFont("NotoSans-Bold", FONTS / "NotoSans-Bold.ttf"))
        pdfmetrics.registerFontFamily("NotoSans", normal="NotoSans", bold="NotoSans-Bold")
    heading = ParagraphStyle(
        "title", fontName="NotoSans-Bold", fontSize=16, leading=20, spaceAfter=12
    )
    body = ParagraphStyle("turn", fontName="NotoSans", fontSize=11, leading=15, spaceAfter=8)
    story = [Paragraph(escape(title), heading)]
    for turn in t.turns:
        who = escape(t.display_name(turn.speaker))
        story.append(Paragraph(f"<b>{who}:</b> {escape(turn.text)}", body))
    out = io.BytesIO()
    SimpleDocTemplate(
        out, pagesize=A4, title=title, author="", creator="WaveMaterial",
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
        invariant=True,
    ).build(story)  # fmt: skip
    return out.getvalue()
