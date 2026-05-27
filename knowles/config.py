"""Configuration: merges config.yaml with environment / secrets."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv optional at runtime
    pass

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
EPISODES = ROOT / "episodes"


@lru_cache(maxsize=1)
def _yaml() -> dict[str, Any]:
    path = ROOT / "config.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def cfg(*keys: str, default: Any = None) -> Any:
    """Fetch a nested value from config.yaml, e.g. cfg('video', 'fps')."""
    node: Any = _yaml()
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def require_env(name: str) -> str:
    val = env(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in .env (local) or repo Secrets (GitHub Actions)."
        )
    return val


def gemini_api_key() -> str:
    return require_env("GEMINI_API_KEY")


def privacy_status() -> str:
    return env("KNOWLES_PRIVACY") or cfg("publish", "privacy", default="private")


def publish_at() -> str | None:
    return env("KNOWLES_PUBLISH_AT")


def load_json_secret(env_name: str, file_fallback: str) -> dict[str, Any] | None:
    """Read JSON from an env var (preferred for CI) or a local file."""
    raw = env(env_name)
    if raw:
        return json.loads(raw)
    path = ROOT / file_fallback
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def episode_dir(slug: str) -> Path:
    d = EPISODES / slug
    d.mkdir(parents=True, exist_ok=True)
    return d
