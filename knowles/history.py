"""Ledger of produced episodes, committed to the repo as produced.json.

Two jobs:
  * give Stage 1 a list of already-covered stories so it never re-suggests them,
  * keep a simple record (date, hook, title, url) of what has shipped.

The produce workflow commits produced.json back to the repo after a build so
the ledger persists across runs.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from . import config

LEDGER: Path = config.ROOT / "produced.json"


def load() -> list[dict]:
    if LEDGER.exists():
        try:
            data = json.loads(LEDGER.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def recent_hooks(n: int = 60) -> list[str]:
    """The most recent N covered hooks/titles, for Stage 1 to avoid."""
    out: list[str] = []
    for e in load():
        hook = (e.get("hook") or e.get("title") or "").strip()
        if hook:
            out.append(hook)
    return out[-n:]


def already_covered(hook: str) -> bool:
    norm = re.sub(r"[^a-z0-9]+", " ", hook.lower()).strip()
    for h in recent_hooks():
        if re.sub(r"[^a-z0-9]+", " ", h.lower()).strip() == norm:
            return True
    return False


def record(slug: str, hook: str, title: str, url: str | None = None) -> None:
    hist = load()
    hist.append(
        {
            "date": f"{date.today():%Y-%m-%d}",
            "slug": slug,
            "hook": hook,
            "title": title,
            "url": url,
        }
    )
    LEDGER.write_text(json.dumps(hist, indent=2, ensure_ascii=False), encoding="utf-8")
