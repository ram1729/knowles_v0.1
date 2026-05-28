"""Stage 1 — find 3 candidate stories with Search grounding."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import config, gemini_client
from .prompts import STAGE1_FIND, STAGE1_JSON_ADDENDUM


@dataclass
class Candidate:
    id: int
    hook: str
    summary: str
    unreal: str = ""
    lesson: str = ""
    sources: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        return cls(
            id=int(d.get("id", 0)),
            hook=str(d.get("hook", "")).strip(),
            summary=str(d.get("summary", "")).strip(),
            unreal=str(d.get("unreal", "")).strip(),
            lesson=str(d.get("lesson", "")).strip(),
            sources=[str(s).strip() for s in d.get("sources", []) if str(s).strip()],
        )

    def story_and_sources(self) -> str:
        lines = [f"HOOK: {self.hook}", f"SUMMARY: {self.summary}"]
        if self.unreal:
            lines.append(f"THE 'CAN'T BE REAL' ELEMENT: {self.unreal}")
        if self.lesson:
            lines.append(f"LESSON: {self.lesson}")
        if self.sources:
            lines.append("SOURCES:\n" + "\n".join(f"- {s}" for s in self.sources))
        return "\n".join(lines)


_JSON_BLOCK = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _extract_candidates(text: str) -> list[Candidate]:
    blocks = _JSON_BLOCK.findall(text)
    if not blocks:
        raise ValueError("Stage 1 output contained no ```json block of candidates.")
    data = json.loads(blocks[-1])
    if not isinstance(data, list) or not data:
        raise ValueError("Stage 1 JSON block was not a non-empty array.")
    return [Candidate.from_dict(d) for d in data]


def _recency_clause() -> str:
    days = int(config.cfg("show", "recency_days", default=7))
    today = date.today()
    since = today - timedelta(days=days)
    return (
        f"It MUST be fresh: the events and/or the major news coverage occurred on or after "
        f"{since:%Y-%m-%d} — within the last {days} days as of {today:%Y-%m-%d}. State each "
        f"story's publication date and outlet. Do NOT suggest older, evergreen, or "
        f"previously-famous cases (e.g. well-worn stories from past years)."
    )


def _exclusions_block(exclude: list[str] | None) -> str:
    if not exclude:
        return ""
    bullets = "\n".join(f"- {h}" for h in exclude)
    return (
        "\n\n**ALREADY COVERED — do NOT suggest these or close variants of them "
        "(pick genuinely different stories):**\n" + bullets + "\n"
    )


def find(exclude: list[str] | None = None) -> tuple[str, list[Candidate]]:
    """Return (human_markdown, candidates). The markdown keeps the scout's full
    write-up minus the machine JSON block.

    `exclude` is a list of already-covered hooks/titles the scout must avoid.
    """
    today = date.today()
    preamble = f"Today's date is {today:%Y-%m-%d}. Use web search to find genuinely recent stories.\n\n"
    body = STAGE1_FIND.format(recency_clause=_recency_clause())
    prompt = preamble + body + _exclusions_block(exclude) + STAGE1_JSON_ADDENDUM

    raw = gemini_client.generate_text(prompt, use_search=True, temperature=0.9)
    candidates = _extract_candidates(raw)
    markdown = _JSON_BLOCK.sub("", raw).strip()
    return markdown, candidates
