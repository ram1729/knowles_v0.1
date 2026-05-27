"""Stage 2 — verify the chosen story into a fact-sheet (Search grounding)."""
from __future__ import annotations

from dataclasses import dataclass

from . import gemini_client
from .prompts import STAGE2_VERIFY


@dataclass
class FactSheet:
    text: str
    proceed: bool
    reason: str = ""


def verify(story_and_sources: str) -> FactSheet:
    prompt = STAGE2_VERIFY.format(story_and_sources=story_and_sources)
    # Lower temperature: this is a factual task, not a creative one.
    text = gemini_client.generate_text(prompt, use_search=True, temperature=0.3)

    # The hard gate: the verifier writes "DO NOT PROCEED" at the top when the
    # core fact isn't confirmed by 2+ independent credible sources.
    head = text[:400].upper()
    if "DO NOT PROCEED" in head:
        return FactSheet(text=text, proceed=False, reason="Verifier flagged: core fact unverified.")
    return FactSheet(text=text, proceed=True)
