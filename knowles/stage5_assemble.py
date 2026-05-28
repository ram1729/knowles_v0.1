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
    """Concatenate a short intro sting + narration + a short outro sting.

    The intro/outro music files are trimmed to the first N seconds (config
    audio.intro_seconds / audio.outro_seconds) with gentle fades, rather than
    playing the whole track.
    """
    intro = config.ASSETS / "intro.mp3"
    outro = config.ASSETS / "outro.mp3"
    intro_s = float(config.cfg("audio", "intro_seconds", default=5))
    outro_s = float(config.cfg("audio", "outro_seconds", default=5))

    # (path, trim_seconds | None). None means "use the whole file" (narration).
    segments: list[tuple[Path, float | None]] = []
    if intro.exists():
        segments.append((intro, intro_s))
    segments.append((narration, None))
    if outro.exists():
        segments.append((outro, outro_s))

    cmd = [_ffmpeg(), "-y"]
    for path, _ in segments:
        cmd += ["-i", str(path)]

    chains = []
    for i, (_, trim) in enumerate(segments):
        f = f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo"
        if trim:
            fade_out_at = max(0.0, trim - 0.8)
            f += (
                f",atrim=0:{trim},asetpts=N/SR/TB"
                f",afade=t=in:st=0:d=0.3,afade=t=out:st={fade_out_at}:d=0.8"
            )
        f += f"[a{i}]"
        chains.append(f)

    chain_labels = "".join(f"[a{i}]" for i in range(len(segments)))
    filt = ";".join(chains) + f";{chain_labels}concat=n={len(segments)}:v=0:a=1[out]"
    cmd += ["-filter_complex", filt, "-map", "[out]", "-c:a", "libmp3lame", "-q:a", "3", str(out_mp3)]

    if len(segments) == 1:
        _run(cmd)
        return out_mp3
    # With music: try the full sting+narration+sting concat; if it fails, fall
    # back to narration-only so the episode still ships.
    try:
        _run(cmd)
    except RuntimeError as exc:
        print(f"[warn] intro/outro mix failed, using narration only: {exc}", file=__import__("sys").stderr)
        _run([_ffmpeg(), "-y", "-i", str(narration), "-c:a", "libmp3lame", "-q:a", "3", str(out_mp3)])
    return out_mp3


def build_video(audio: Path, subtitles: Path | None, out_mp4: Path, background: Path | None = None) -> Path:
    """Render a static-visual MP4 with burned-in captions, matched to audio length.

    `subtitles` may be a styled .ass (preferred — carries its own large
    left-column style) or a plain .srt (a default style is forced on).

    Visual source priority:
      1. `background` (the episode video plate) — persists for the whole video,
      2. assets/background.png,
      3. a solid colour from config.
    """
    w = int(config.cfg("video", "width", default=1920))
    h = int(config.cfg("video", "height", default=1080))
    fps = int(config.cfg("video", "fps", default=24))
    bg_color = config.cfg("video", "bg_color", default="0b0d12")
    asset_bg = config.ASSETS / "background.png"

    if background and background.exists():
        bg_img: Path | None = background
    elif asset_bg.exists():
        bg_img = asset_bg
    else:
        bg_img = None

    work = out_mp4.parent
    base_vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}"
    )

    # Build the optional captions clause.
    caption_vf = ""
    if subtitles and subtitles.exists():
        # Run with cwd at the work dir and reference the bare filename to dodge
        # Windows drive-letter colon escaping inside the filter graph.
        is_ass = subtitles.suffix.lower() == ".ass"
        local = work / ("captions.ass" if is_ass else "captions.srt")
        if subtitles.resolve() != local.resolve():
            shutil.copyfile(subtitles, local)
        fonts = ":fontsdir=/usr/share/fonts" if Path("/usr/share/fonts").exists() else ""
        if is_ass:
            caption_vf = f",subtitles={local.name}{fonts}"  # .ass carries its own style
        else:
            style = "FontName=DejaVu Serif,Fontsize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,MarginV=60,Alignment=2"
            caption_vf = f",subtitles={local.name}{fonts}:force_style='{style}'"

    def _cmd(vf: str) -> list[str]:
        c = [_ffmpeg(), "-y"]
        if bg_img is not None:
            c += ["-loop", "1", "-i", str(bg_img)]
        else:
            c += ["-f", "lavfi", "-i", f"color=c=0x{bg_color}:s={w}x{h}:r={fps}"]
        c += ["-i", str(audio), "-vf", vf,
              "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", str(fps),
              "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_mp4.name)]
        return c

    # Try with captions; if the burn fails (e.g. libass/font issue), still ship
    # a clean captionless video rather than losing the whole episode.
    if caption_vf:
        try:
            _run(_cmd(base_vf + caption_vf), cwd=work)
            return out_mp4
        except RuntimeError as exc:
            print(f"[warn] caption burn failed, rendering without captions: {exc}", file=__import__("sys").stderr)
    _run(_cmd(base_vf), cwd=work)
    return out_mp4
