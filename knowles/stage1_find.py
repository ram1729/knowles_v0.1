"""Stage 1 — find 3 candidate stories with Search grounding."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import gemini_client
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


def find() -> tuple[str, list[Candidate]]:
    """Return (human_markdown, candidates). The markdown keeps the scout's full
    write-up minus the machine JSON block."""
    prompt = STAGE1_FIND + STAGE1_JSON_ADDENDUM
    raw = gemini_client.generate_text(prompt, use_search=True, temperature=0.9)
    candidates = _extract_candidates(raw)
    markdown = _JSON_BLOCK.sub("", raw).strip()
    return markdown, candidates
