"""Stage 6 — thumbnail. Generates a concept, then renders it.

Engines (config: thumbnail.engine):
  * "hybrid" (default, FREE): a free AI background scene (Pollinations, no API
    key) + Gregory cut out of the saved reference portrait, composited on top
    with the title words. Cinematic scenes, but his exact face every week.
  * "nano_banana": Gemini image model using the portrait as reference (may need
    billing on your key).
  * "pillow": the no-network composite (vignette over the portrait + title).

Whatever the engine, this never hard-fails: each step degrades to the next so a
thumbnail is always produced.
"""
from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

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

PORTRAIT = "knowles_portrait.png"
CUTOUT = "knowles_cutout.png"  # optional pre-made transparent PNG (skips rembg)


@dataclass
class Concept:
    scene: str
    title_words: str
    side: str
    video_title: str


# --------------------------------------------------------------------------- #
# concept
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# drawing helpers
# --------------------------------------------------------------------------- #
def _load_font(size: int):
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


def _seed_from(text: str) -> int:
    # Deterministic per episode (Math.random-free), but varies between stories.
    return abs(hash(text)) % 1_000_000


def _gradient_bg(w: int, h: int) -> Image.Image:
    top, bottom = (16, 20, 30), (6, 7, 11)
    base = Image.new("RGB", (w, h))
    px = base.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        px_row = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = px_row
    return base


def _vignette(img: Image.Image) -> Image.Image:
    """Darken the edges for a cinematic, focused frame."""
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-w * 0.18, -h * 0.18, w * 1.18, h * 1.18], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(int(min(w, h) * 0.16)))
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(img.convert("RGB"), dark, mask)


def _noir_grade(img: Image.Image) -> Image.Image:
    """House look: desaturated, high-contrast, dimmed, faint warm tint, vignette."""
    img = img.convert("RGB")
    img = ImageEnhance.Color(img).enhance(0.55)
    img = ImageEnhance.Contrast(img).enhance(1.18)
    img = ImageEnhance.Brightness(img).enhance(0.82)
    r, g, b = img.split()
    r = r.point(lambda v: min(255, int(v * 1.06)))
    b = b.point(lambda v: int(v * 0.92))
    img = Image.merge("RGB", (r, g, b))
    return _vignette(img)


def _hand_drawn_underline(draw, x0: int, x1: int, y: int, color, *, amp: float = 4.0, weight: int = 6) -> None:
    """A loose, slightly wavy marker underline (deterministic sine wobble)."""
    span = max(1, x1 - x0)
    pts = []
    steps = max(8, span // 14)
    for i in range(steps + 1):
        t = i / steps
        x = x0 + t * span
        # gentle wave + a slight downward sag, like a real pen stroke
        wob = math.sin(t * math.pi * 2.2) * amp + math.sin(t * math.pi) * (amp * 0.6)
        pts.append((x, y + wob))
    # draw a couple of overlapping passes for a marker feel
    for off in (0, 2):
        draw.line([(px, py + off) for px, py in pts], fill=color, width=weight, joint="curve")


def _draw_title(base: Image.Image, words: str, *, text_side: str) -> Image.Image:
    """Draw the title on the half opposite Knowles, with an outline and a
    hand-drawn amber underline beneath the last line (house style)."""
    w, h = base.size
    draw = ImageDraw.Draw(base)
    font = _load_font(int(h * 0.155))           # bigger, poster-scale
    col_w = int(w * 0.52)
    margin = int(w * 0.055)
    lines = _wrap(draw, words, font, col_w) or [words]

    while len(lines) > 3 and font.size > 24:
        font = _load_font(int(font.size * 0.88))
        lines = _wrap(draw, words, font, col_w)

    line_h = draw.textbbox((0, 0), "Ay", font=font)[3] + int(h * 0.012)
    total_h = line_h * len(lines)
    y = (h - total_h) // 2
    x0 = margin if text_side == "left" else (w - col_w - margin)
    last_extent = (x0, x0 + col_w, y)
    for line in lines:
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-3, -3), (3, 3), (-3, 3), (3, -3)):
            draw.text((x0 + dx, y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((x0, y), line, font=font, fill=(255, 240, 210))
        bbox = draw.textbbox((x0, y), line, font=font)
        last_extent = (x0, bbox[2], bbox[3])
        y += line_h

    # Hand-drawn underline beneath the final line, warm amber.
    lx0, lx1, ly = last_extent
    _hand_drawn_underline(draw, lx0, lx1, ly + int(h * 0.02), (240, 176, 64),
                          amp=max(3.0, h * 0.006), weight=max(5, int(h * 0.010)))
    return base


# --------------------------------------------------------------------------- #
# free AI background (Pollinations — no API key, no signup)
# --------------------------------------------------------------------------- #
def _pollinations_bg(scene: str, w: int, h: int, seed: int) -> Image.Image | None:
    style = config.cfg("thumbnail", "style_line", default="").strip()
    model = config.cfg("thumbnail", "pollinations_model", default="flux")
    prompt = (
        f"{scene}. Cinematic establishing shot, no readable text, no watermark, "
        f"no portrait of a person's face in the foreground. {style}"
    )
    url = (
        "https://image.pollinations.ai/prompt/"
        + urllib.parse.quote(prompt, safe="")
        + f"?width={w}&height={h}&seed={seed}&model={urllib.parse.quote(model)}&nologo=true"
    )
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "knowles-files/0.1"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
            if data and len(data) > 1024:
                return _cover(Image.open(BytesIO(data)), w, h)
        except Exception:
            if attempt == 2:
                return None
    return None


# --------------------------------------------------------------------------- #
# Knowles cutout (transparent PNG of just him)
# --------------------------------------------------------------------------- #
def _knowles_cutout() -> Image.Image | None:
    """Prefer a pre-made transparent assets/knowles_cutout.png. Otherwise try
    rembg on the portrait. Otherwise None (caller feathers the portrait)."""
    cutout = config.ASSETS / CUTOUT
    if cutout.exists():
        try:
            return Image.open(cutout).convert("RGBA")
        except Exception:
            pass

    portrait = config.ASSETS / PORTRAIT
    if not portrait.exists():
        return None
    try:
        from rembg import remove  # optional, best-effort

        cut = remove(Image.open(portrait).convert("RGBA"))
        if isinstance(cut, Image.Image):
            return cut.convert("RGBA")
        return Image.open(BytesIO(cut)).convert("RGBA")  # bytes form
    except Exception:
        return None


def _trim_alpha(img: Image.Image) -> Image.Image:
    bbox = img.split()[-1].getbbox()
    return img.crop(bbox) if bbox else img


def _paste_knowles(base: Image.Image, person: Image.Image, side: str) -> Image.Image:
    w, h = base.size
    person = _trim_alpha(person)
    target_h = int(h * 0.98)
    scale = target_h / person.height
    person = person.resize((max(1, int(person.width * scale)), target_h), Image.LANCZOS)
    if person.width > int(w * 0.6):
        scale2 = int(w * 0.6) / person.width
        person = person.resize((int(w * 0.6), int(person.height * scale2)), Image.LANCZOS)

    x = int(w * 0.02) if side == "left" else w - person.width - int(w * 0.02)
    y = h - person.height

    # Soft shadow for separation from the AI background.
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sil = Image.new("RGBA", person.size, (0, 0, 0, 150))
    shadow.paste(sil, (x + 10, y + 8), person)
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    base = Image.alpha_composite(base.convert("RGBA"), shadow)
    base.paste(person, (x, y), person)
    return base


def _darken_for_text(base: Image.Image, text_side: str) -> Image.Image:
    """Gradient scrim on the text side so words stay legible over any scene."""
    w, h = base.size
    scrim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    half = int(w * 0.62)
    for x in range(half):
        a = int(150 * (1 - x / half)) if text_side == "left" else 0
        if text_side == "left":
            sd.line([(x, 0), (x, h)], fill=(0, 0, 0, a))
    if text_side == "right":
        for x in range(w - half, w):
            a = int(150 * ((x - (w - half)) / half))
            sd.line([(x, 0), (x, h)], fill=(0, 0, 0, a))
    return Image.alpha_composite(base.convert("RGBA"), scrim)


# --------------------------------------------------------------------------- #
# composers
# --------------------------------------------------------------------------- #
def _render_thumbnail(base: Image.Image, person: Image.Image | None, concept: Concept, out_path: Path) -> None:
    """The unique noir thumbnail: cinematic graded scene, Gregory on the RIGHT,
    big serif title on the LEFT with a hand-drawn amber underline."""
    base = _noir_grade(base)
    base = _darken_for_text(base, "left")          # extra scrim so the title pops
    if person is not None:
        base = _paste_knowles(base, person, "right")
    base = _draw_title(base, concept.title_words, text_side="left")
    base.convert("RGB").save(out_path, "PNG")


def _compose_pillow(concept: Concept, out_path: Path) -> tuple[Path, str]:
    w = int(config.cfg("thumbnail", "width", default=1280))
    h = int(config.cfg("thumbnail", "height", default=720))
    portrait = config.ASSETS / PORTRAIT

    base = _cover(Image.open(portrait), w, h) if portrait.exists() else _gradient_bg(w, h)

    # Vignette + lower scrim for legibility.
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([0, int(h * 0.58), w, h], fill=(0, 0, 0, 175))
    base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(base)
    font = _load_font(int(h * 0.13))
    margin = int(w * 0.05)
    lines = _wrap(draw, concept.title_words, font, w - 2 * margin)
    line_h = draw.textbbox((0, 0), "Ay", font=font)[3] + int(h * 0.01)
    y = h - line_h * len(lines) - int(h * 0.06)
    for line in lines:
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, 2)):
            draw.text((margin + dx, y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((margin, y), line, font=font, fill=(255, 255, 255))
        y += line_h

    base.save(out_path, "PNG")
    return out_path, "pillow"


def _compose_nano_banana(concept: Concept, out_path: Path) -> tuple[Path, str] | None:
    portrait = config.ASSETS / PORTRAIT
    if not portrait.exists():
        return None
    w = int(config.cfg("thumbnail", "width", default=1280))
    h = int(config.cfg("thumbnail", "height", default=720))
    style = config.cfg("thumbnail", "style_line", default="").strip()
    prompt = THUMBNAIL_STANDING.format(
        scene=concept.scene, side=concept.side, style_line=style, title_words=concept.title_words
    )
    try:
        data = gemini_client.generate_image(prompt, str(portrait))
        if data:
            _cover(Image.open(BytesIO(data)), w, h).save(out_path, "PNG")
            return out_path, "nano_banana"
    except Exception:
        return None
    return None


# --------------------------------------------------------------------------- #
# public entry
# --------------------------------------------------------------------------- #
def build_thumbnail(concept: Concept, out_path: Path) -> tuple[Path, str]:
    """Produce the unique, scroll-stopping NOIR thumbnail (YouTube still).

    Returns (path, method). Engine chosen by config thumbnail.engine; always
    degrades gracefully so a thumbnail is produced.
    """
    engine = str(config.cfg("thumbnail", "engine", default="hybrid")).lower()
    w = int(config.cfg("thumbnail", "width", default=1280))
    h = int(config.cfg("thumbnail", "height", default=720))

    if engine == "nano_banana":
        result = _compose_nano_banana(concept, out_path)
        if result:
            return result
        engine = "hybrid"  # model declined/errored — fall through

    if engine == "pillow":
        return _compose_pillow(concept, out_path)

    # default: hybrid noir — unique AI scene + graded + Gregory + title.
    try:
        bg = _pollinations_bg(concept.scene, w, h, _seed_from(concept.title_words))
        bg_method = "ai" if bg is not None else "gradient"
        base = bg if bg is not None else _gradient_bg(w, h)
        person = _knowles_cutout()
        _render_thumbnail(base, person, concept, out_path)
        return out_path, f"hybrid_noir_{bg_method}" + ("" if person is not None else "_nocutout")
    except Exception:
        return _compose_pillow(concept, out_path)
