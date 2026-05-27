"""Build an SRT subtitle file from the script, timed against the narration length.

Gemini TTS does not return word timestamps, so cues are distributed proportionally
to their character count across the narration duration. Good enough for a static
visual; the rhythm tracks the spoken text closely.
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


def _ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(script: str, duration: float, out_path: Path, *, start_offset: float = 0.0) -> Path:
    """Write an SRT covering `duration` seconds, starting at `start_offset`
    (use the intro-music length so captions line up with the narration)."""
    max_chars = int(config.cfg("captions", "max_chars_per_cue", default=84))
    cues = _cues(script, max_chars) or [script.strip()]
    total_chars = sum(len(c) for c in cues) or 1

    lines: list[str] = []
    t = start_offset
    for i, cue in enumerate(cues, start=1):
        share = len(cue) / total_chars
        dur = share * duration
        start, end = t, t + dur
        lines.append(str(i))
        lines.append(f"{_ts(start)} --> {_ts(end)}")
        lines.append(cue)
        lines.append("")
        t = end

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
