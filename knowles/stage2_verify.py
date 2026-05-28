"""Stage 2 — verify the chosen story into a fact-sheet (Search grounding)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import gemini_client
from .prompts import STAGE2_VERIFY

# The verifier ends with an explicit, machine-readable verdict line.
_VERDICT = re.compile(r"VERDICT:\s*(PROCEED|DO[_ ]?NOT[_ ]?PROCEED)", re.IGNORECASE)


@dataclass
class FactSheet:
    text: str
    proceed: bool
    reason: str = ""


def _decide(text: str) -> tuple[bool, str]:
    """Return (proceed, reason). Trust the explicit final VERDICT line; fall
    back to a careful heuristic only if the model forgot to emit one."""
    matches = _VERDICT.findall(text)
    if matches:
        verdict = matches[-1].upper().replace(" ", "_")
        if "NOT" in verdict:
            return False, "Verifier verdict: DO_NOT_PROCEED (core fact unverified)."
        return True, ""

    # Fallback: no verdict line. Only block when the text clearly signals the
    # core fact is NOT confirmed — and there's no confirming language. This
    # avoids the old false positive where the template's example heading
    # ("DO NOT PROCEED — core fact unverified") was echoed before an approval.
    upper = text.upper()
    head = upper[:300]
    says_stop = "DO NOT PROCEED" in head or "DO_NOT_PROCEED" in head
    says_go = any(s in upper for s in ("MAY PROCEED", "YOU MAY PROCEED", "✅ CONFIRMED", "IS CONFIRMED"))
    if says_stop and not says_go:
        return False, "Verifier indicated the core fact is unverified (no explicit verdict line)."
    return True, ""


def verify(story_and_sources: str) -> FactSheet:
    prompt = STAGE2_VERIFY.format(story_and_sources=story_and_sources)
    # Lower temperature: this is a factual task, not a creative one.
    text = gemini_client.generate_text(prompt, use_search=True, temperature=0.3)
    proceed, reason = _decide(text)
    return FactSheet(text=text, proceed=proceed, reason=reason)
