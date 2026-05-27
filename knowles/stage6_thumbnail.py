"""Stage 6 — thumbnail. Generates a concept, then renders it.

Primary: Nano Banana (Gemini image) using the saved Knowles reference portrait so
his face stays identical every week. Fallback (no billing / no portrait / model
declines): a local Pillow composite from the portrait + title words.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config, gemini_client
from .prompts import THUMBNAIL_CONCEPT, THUMBNAIL_STANDING

_JSON_OBJ = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_BARE_OBJ = re.compile(r"\{.*\}", re.DOTALL)

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "C:/Windows/Fonts/georgiab.ttf",
    "C:/Windows/Fonts/timesbd.ttf",
    "/Library/Fonts/Georgia Bold.ttf",
]


@dataclass
class Concept:
    scene: str
    title_words: str
    side: str
    video_title: str


def _parse_concept(text: str) -> Concept:
    m = _JSON_OBJ.search(text)
    if m:
        raw = m.group(1)
    else:
        bare = _BARE_OBJ.search(text)
        raw = bare.group(0) if bare else "{}"
    data = json.loads(raw)
    side = str(data.get("side", "left")).lower()
    return Concept(
        scene=str(data.get("scene", "Gregory Knowles facing an unseen threat")).strip(),
        title_words=str(data.get("title_words", "THE FILE")).strip().strip(".").upper(),
        side="right" if side == "right" else "left",
        video_title=str(data.get("video_title", "The Knowles Files")).strip()[:100],
    )


def concept_for(script: str) -> Concept:
    text = gemini_client.generate_text(THUMBNAIL_CONCEPT.format(script=script), temperature=0.7)
    try:
        return _parse_concept(text)
    except Exception:
        return Concept("Gregory Knowles facing an unseen threat", "THE FILE", "left", "The Knowles Files")


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.convert("RGB")
    scale = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _compose_fallback(concept: Concept, out_path: Path) -> Path:
    w = int(config.cfg("thumbnail", "width", default=1280))
    h = int(config.cfg("thumbnail", "height", default=720))
    portrait = config.ASSETS / "knowles_portrait.png"

    if portrait.exists():
        base = _cover(Image.open(portrait), w, h)
    else:
        base = Image.new("RGB", (w, h), (11, 13, 18))

    # Darken for text legibility.
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([0, int(h * 0.62), w, h], fill=(0, 0, 0, 170))
    base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(base)
    font = _load_font(int(h * 0.13))
    margin = int(w * 0.05)
    lines = _wrap(draw, concept.title_words, font, w - 2 * margin)
    line_h = draw.textbbox((0, 0), "Ay", font=font)[3] + int(h * 0.01)
    total_h = line_h * len(lines)
    y = h - total_h - int(h * 0.06)
    for line in lines:
        x = margin
        # Outline for contrast.
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, 2)):
            draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += line_h

    base.save(out_path, "PNG")
    return out_path


def build_thumbnail(concept: Concept, out_path: Path) -> tuple[Path, str]:
    """Return (path, method) where method is 'nano_banana' or 'fallback'."""
    portrait = config.ASSETS / "knowles_portrait.png"
    w = int(config.cfg("thumbnail", "width", default=1280))
    h = int(config.cfg("thumbnail", "height", default=720))
    style = config.cfg("thumbnail", "style_line", default="").strip()

    if portrait.exists():
        prompt = THUMBNAIL_STANDING.format(
            scene=concept.scene, side=concept.side, style_line=style, title_words=concept.title_words
        )
        try:
            data = gemini_client.generate_image(prompt, str(portrait))
            if data:
                img = _cover(Image.open(BytesIO(data)), w, h)
                img.save(out_path, "PNG")
                return out_path, "nano_banana"
        except Exception:
            pass  # fall through to local composite

    return _compose_fallback(concept, out_path), "fallback"
