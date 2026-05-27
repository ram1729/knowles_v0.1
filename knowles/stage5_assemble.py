"""Stage 5 — assemble audio + video with ffmpeg.

Builds:
  - episode.mp3  : [intro?] + narration + [outro?]   (audio-only release)
  - episode.mp4  : static visual + the same audio + burned-in captions

Intro/outro music and a background image are optional. If they're missing the
pipeline still produces a clean MP3 and an MP4 over a solid-colour background.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import config


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH. Install it (the GitHub Actions runner does this automatically).")
    return exe


def _ffprobe() -> str | None:
    return shutil.which("ffprobe")


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-25:])
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}):\n{tail}")


def probe_duration(path: Path) -> float:
    probe = _ffprobe()
    if not probe:
        return 0.0
    proc = subprocess.run(
        [probe, "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return 0.0
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def build_audio(narration: Path, out_mp3: Path) -> Path:
    """Concatenate optional intro + narration + optional outro into one MP3."""
    intro = config.ASSETS / "intro.mp3"
    outro = config.ASSETS / "outro.mp3"
    parts = [p for p in (intro if intro.exists() else None, narration, outro if outro.exists() else None) if p]

    cmd = [_ffmpeg(), "-y"]
    for p in parts:
        cmd += ["-i", str(p)]

    norm = "".join(
        f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{i}];" for i in range(len(parts))
    )
    chain = "".join(f"[a{i}]" for i in range(len(parts)))
    filt = f"{norm}{chain}concat=n={len(parts)}:v=0:a=1[out]"
    cmd += ["-filter_complex", filt, "-map", "[out]", "-c:a", "libmp3lame", "-q:a", "3", str(out_mp3)]
    _run(cmd)
    return out_mp3


def build_video(audio: Path, srt: Path | None, out_mp4: Path) -> Path:
    """Render a static-visual MP4 with burned-in captions, matched to audio length."""
    w = int(config.cfg("video", "width", default=1920))
    h = int(config.cfg("video", "height", default=1080))
    fps = int(config.cfg("video", "fps", default=24))
    bg_color = config.cfg("video", "bg_color", default="0b0d12")
    bg_img = config.ASSETS / "background.png"

    work = out_mp4.parent
    cmd = [_ffmpeg(), "-y"]
    if bg_img.exists():
        cmd += ["-loop", "1", "-i", str(bg_img)]
    else:
        cmd += ["-f", "lavfi", "-i", f"color=c=0x{bg_color}:s={w}x{h}:r={fps}"]
    cmd += ["-i", str(audio)]

    # Scale/pad the visual to the target frame, then optionally burn captions.
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}"
    if srt and srt.exists():
        # Run with cwd at the work dir and reference the bare filename to dodge
        # Windows drive-letter colon escaping inside the filter graph.
        local = work / "captions.srt"
        if srt.resolve() != local.resolve():
            shutil.copyfile(srt, local)
        style = "FontName=DejaVu Serif,Fontsize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,MarginV=60,Alignment=2"
        vf += f",subtitles=captions.srt:force_style='{style}'"

    cmd += [
        "-vf", vf,
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(out_mp4.name),
    ]
    _run(cmd, cwd=work)
    return out_mp4
