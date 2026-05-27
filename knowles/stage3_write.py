"""Stage 3 — write the spoken-word script from the verified fact-sheet."""
from __future__ import annotations

import re

from . import gemini_client
from .prompts import STAGE3_WRITE

# Lines the model occasionally leaks despite "output only spoken words".
_STAGE_DIRECTION = re.compile(r"^\s*(\[.*?\]|\(.*?\)|#{1,6}\s|\*{1,3}[A-Z ]+\*{1,3}\s*$)")


def _clean(script: str) -> str:
    out = []
    for line in script.splitlines():
        if _STAGE_DIRECTION.match(line):
            continue
        out.append(line)
    # Collapse 3+ blank lines to a paragraph break.
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def write(fact_sheet: str) -> str:
    prompt = STAGE3_WRITE.format(fact_sheet=fact_sheet)
    script = gemini_client.generate_text(prompt, use_search=False, temperature=0.95)
    return _clean(script)
