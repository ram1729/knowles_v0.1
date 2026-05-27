"""Stage 4 — narrate the script with the frozen Alnilam voice + director's note."""
from __future__ import annotations

from pathlib import Path

from . import config, gemini_client


def _chunk(script: str, limit: int) -> list[str]:
    """Split into TTS-sized chunks on paragraph boundaries (never mid-sentence)."""
    paras = [p.strip() for p in script.split("\n\n") if p.strip()]
    chunks: list[str] = []
    cur = ""
    for para in paras:
        if cur and len(cur) + len(para) + 2 > limit:
            chunks.append(cur)
            cur = para
        elif cur:
            cur += "\n\n" + para
        else:
            cur = para
        # A single paragraph longer than the limit: hard-split on sentences.
        while len(cur) > limit:
            cut = cur.rfind(". ", 0, limit)
            cut = cut + 1 if cut > limit // 2 else limit
            chunks.append(cur[:cut].strip())
            cur = cur[cut:].strip()
    if cur:
        chunks.append(cur)
    return chunks


def narrate(script: str, out_path: Path) -> tuple[Path, float]:
    """Render the whole script to a WAV. Returns (path, duration_seconds)."""
    voice = config.cfg("voice", "name", default="Alnilam")
    note = config.cfg("voice", "director_note", default="").strip()
    sr = int(config.cfg("audio", "sample_rate", default=24000))
    limit = int(config.cfg("audio", "tts_chunk_chars", default=1800))

    gap = b"\x00" * int(sr * 2 * 0.35)  # 350ms of silence between chunks
    chunks = _chunk(script, limit)
    pcm = bytearray()
    for i, chunk in enumerate(chunks):
        prompt = f"{note}\n\n{chunk}" if note else chunk
        pcm += gemini_client.generate_speech_pcm(prompt, voice)
        if i < len(chunks) - 1:
            pcm += gap

    wav = gemini_client.pcm_to_wav(bytes(pcm), sr)
    out_path.write_bytes(wav)
    duration = len(pcm) / (sr * 2)
    return out_path, duration
