"""Stage 3b — fabricate a FAKE story brief for the Real-or-Rubbish game.

The output is a brief in the same shape as a verified fact-sheet, so the game
writer dramatizes it identically to a true one. It is fiction by design and
fully anonymized (no proper names), so it can never defame anyone.
"""
from __future__ import annotations

from . import gemini_client
from .prompts import STAGE_FAKE


def fabricate() -> str:
    # Higher temperature: we want an inventive, varied, convincing tale.
    return gemini_client.generate_text(STAGE_FAKE, use_search=False, temperature=1.1)
