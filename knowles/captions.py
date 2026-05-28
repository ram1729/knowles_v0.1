"""Build subtitle files from the script, timed against the narration length.

Gemini TTS does not return word timestamps, so cues are distributed proportionally
to their character count across the narration duration. Good enough for a static
visual; the rhythm tracks the spoken text closely.

We emit two files:
  * captions.srt — standard, for uploading to YouTube as a selectable track.
  * captions.ass — styled for burning into the video: large, left-column,
    senior-friendly text pinned over the darkened left caption stage.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config

_SENTENCE_END = (".", "!", "?", "…")


def _cues(script: str, max_chars: int) -> list[str]:
    text = re.sub(r"\s+", " ", script.replace("\n", " ")).strip()
    words = text.split(" ")
    cues: list[str] = []
    cur = ""
    for word in words:
        candidate = f"{cur} {word}".strip()
        if len(candidate) > max_chars and cur:
            cues.append(cur)
            cur = word
        else:
            cur = candidate
        # Natural break after a sentence end once the cue has some body.
        if cur.endswith(_SENTENCE_END) and len(cur) >= max_chars * 0.5:
            cues.append(cur)
            cur = ""
    if cur:
        cues.append(cur)
    return cues


def _timed_cues(script: str, duration: float, start_offset: float) -> list[tuple[float, float, str]]:
    max_chars = int(config.cfg("captions", "max_chars_per_cue", default=60))
    min_dur = float(config.cfg("captions", "min_cue_seconds", default=1.2))
    cues = _cues(script, max_chars) or [script.strip()]
    total_chars = sum(len(c) for c in cues) or 1

    out: list[tuple[float, float, str]] = []
    t = start_offset
    for cue in cues:
        dur = max(min_dur, (len(cue) / total_chars) * duration)
        out.append((t, t + dur, cue))
        t += dur
    return out


# --------------------------------------------------------------------------- #
# SRT
# --------------------------------------------------------------------------- #
def _ts_srt(seconds: float) -> str:
    seconds = max(0.0, seconds)
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(script: str, duration: float, out_path: Path, *, start_offset: float = 0.0) -> Path:
    """Write an SRT covering `duration` seconds, starting at `start_offset`."""
    lines: list[str] = []
    for i, (start, end, cue) in enumerate(_timed_cues(script, duration, start_offset), start=1):
        lines += [str(i), f"{_ts_srt(start)} --> {_ts_srt(end)}", cue, ""]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------- #
# ASS (styled, burned) — large left-column captions for seniors
# --------------------------------------------------------------------------- #
def _ts_ass(seconds: float) -> str:
    seconds = max(0.0, seconds)
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_ass(text: str) -> str:
    # Curly braces start override blocks in ASS; strip them. Keep it single-line.
    return text.replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def build_ass(script: str, duration: float, out_path: Path, *, start_offset: float = 0.0) -> Path:
    """Write a styled ASS: big serif, left-aligned, vertically centred, confined
    to the left caption column so it sits cleanly over the darkened left stage."""
    w = int(config.cfg("video", "width", default=1920))
    h = int(config.cfg("video", "height", default=1080))
    font = config.cfg("captions", "font_name", default="DejaVu Serif")
    size = int(config.cfg("captions", "font_size", default=56))
    panel_ratio = float(config.cfg("captions", "panel_ratio", default=0.46))

    # Confine text to the left panel. Alignment 4 = middle-left (vertically centred).
    margin_l = int(w * 0.035)
    panel_w = int(w * panel_ratio)
    margin_r = w - panel_w + int(w * 0.02)
    margin_v = int(h * 0.06)

    # Colours are &HAABBGGRR. White fill, black outline, thick for legibility.
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Knowles,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,3,3,2,4,{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, MarginL, MarginR, MarginV, Effect, Text
"""
    # Fields: Layer,Start,End,Style,MarginL,MarginR,MarginV,Effect,Text
    # (0 margins => use the style's margins; Effect empty.)
    rows = [
        f"Dialogue: 0,{_ts_ass(s)},{_ts_ass(e)},Knowles,0,0,0,,{_escape_ass(c)}"
        for s, e, c in _timed_cues(script, duration, start_offset)
    ]
    out_path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    return out_path
