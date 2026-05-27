"""Thin wrapper over the google-genai SDK: text+search, TTS, and image."""
from __future__ import annotations

import io
import time
from functools import lru_cache

from google import genai
from google.genai import types

from . import config


@lru_cache(maxsize=1)
def client() -> "genai.Client":
    return genai.Client(api_key=config.gemini_api_key())


def _retry(fn, *, tries: int = 4, base: float = 4.0):
    """Retry transient failures (free-tier 429s / 5xx) with backoff."""
    last = None
    for attempt in range(tries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - SDK raises varied error types
            last = exc
            msg = str(exc).lower()
            transient = any(t in msg for t in ("429", "rate", "quota", "503", "500", "unavailable", "timeout"))
            if not transient or attempt == tries - 1:
                raise
            time.sleep(base * (2 ** attempt))
    raise last  # pragma: no cover


def generate_text(prompt: str, *, use_search: bool = False, temperature: float = 0.9) -> str:
    """Generate text. When use_search is True, Google Search grounding is enabled."""
    model = config.cfg("models", "text", default="gemini-2.5-flash")
    tools = [types.Tool(google_search=types.GoogleSearch())] if use_search else None
    cfg = types.GenerateContentConfig(temperature=temperature, tools=tools)

    def call():
        resp = client().models.generate_content(model=model, contents=prompt, config=cfg)
        return (resp.text or "").strip()

    return _retry(call)


def generate_speech_pcm(text: str, voice: str) -> bytes:
    """Return raw PCM (24kHz, 16-bit, mono) for one chunk of narration."""
    model = config.cfg("models", "tts", default="gemini-2.5-flash-preview-tts")
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        ),
    )

    def call():
        resp = client().models.generate_content(model=model, contents=text, config=cfg)
        part = resp.candidates[0].content.parts[0]
        data = part.inline_data.data
        if not data:
            raise RuntimeError("TTS returned no audio data")
        return data

    return _retry(call)


def generate_image(prompt: str, reference_image_path: str | None = None) -> bytes | None:
    """Generate an image (Nano Banana). Returns PNG/raw bytes, or None if the model
    declined / returned no image (caller should fall back)."""
    model = config.cfg("models", "image", default="gemini-2.5-flash-image")
    contents: list = [prompt]
    if reference_image_path:
        from PIL import Image

        contents.append(Image.open(reference_image_path))

    def call():
        resp = client().models.generate_content(model=model, contents=contents)
        for part in resp.candidates[0].content.parts:
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return inline.data
        return None

    return _retry(call)


def pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV container."""
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # 16-bit
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()
