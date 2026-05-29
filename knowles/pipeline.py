"""The Knowles Files orchestrator.

Subcommands:
  find      Stage 1 -> 3 candidates (writes candidates.md + candidates.json).
  produce   Stages 2-7 for a chosen candidate (verify, write, voice, assemble,
            thumbnail, publish). Honours the "DO NOT PROCEED" verify gate.
  run       Local interactive: find, pick at the prompt, then produce.

Exit codes: 0 ok, 3 = verify gate said DO NOT PROCEED (a clean "missed week").
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from . import captions, config, gemini_client, history, stage4_voice, stage5_assemble, stage6_thumbnail, stage7_publish
from .stage1_find import Candidate, find
from .stage2_verify import verify
from .stage3_write import write

GATE_EXIT = 3      # verifier said DO NOT PROCEED — a clean "missed week"
PUBLISH_EXIT = 4   # episode built fine, only the YouTube upload failed

_MARKER = "KNOWLES_CANDIDATES"
_MARKER_RE = re.compile(rf"<!--{_MARKER}\s*(.*?)\s*{_MARKER}-->", re.DOTALL)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _slugify(text: str, limit: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:limit].strip("-") or "episode"


def _candidates_payload(candidates: list[Candidate]) -> str:
    return json.dumps([c.__dict__ for c in candidates], ensure_ascii=False)


def _candidates_from_text(text: str) -> list[Candidate]:
    m = _MARKER_RE.search(text)
    raw = m.group(1) if m else text
    return [Candidate.from_dict(d) for d in json.loads(raw)]


def _build_description(candidate: Candidate) -> str:
    """Spoiler-light description. We deliberately don't name the company or
    people in the body — the show's whole point is that you go verify it
    yourself. Sources are kept at the bottom as receipts for those who want
    them after they've tried."""
    parts = [
        "This really happened — but I'll not hand you the names. Gregory never does.",
        "",
        "Pick up your phone, search the story, and see for yourself. "
        "Checking things yourself is a muscle worth keeping strong.",
        "",
    ]
    if candidate.sources:
        parts.append("Did your own digging first? Here are the receipts:")
        parts += [f"- {s}" for s in candidate.sources]
        parts.append("")
    footer = config.cfg("publish", "description_footer", default="")
    if footer:
        parts.append(footer.strip())
    return "\n".join(parts).strip()


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_find(args: argparse.Namespace) -> int:
    markdown, candidates = find(exclude=history.recent_hooks())
    payload = _candidates_payload(candidates)

    body = (
        f"{markdown}\n\n---\n"
        f"**Reply `/produce N`** (N = 1, 2 or 3) on this issue to verify, produce "
        f"and upload that story as a private video. A reply of `/skip` closes the week.\n\n"
        f"<!--{_MARKER}\n{payload}\n{_MARKER}-->\n"
    )
    Path(args.out).write_text(body, encoding="utf-8")
    Path(args.json).write_text(payload, encoding="utf-8")
    print(body)
    print(f"\n[wrote {args.out} and {args.json}]", file=sys.stderr)
    return 0


def _select_candidate(args: argparse.Namespace) -> Candidate:
    if args.candidate_file:
        data = json.loads(Path(args.candidate_file).read_text(encoding="utf-8"))
        return Candidate.from_dict(data)

    text = Path(args.from_body).read_text(encoding="utf-8") if args.from_body else \
        Path(args.candidates_file).read_text(encoding="utf-8")
    candidates = _candidates_from_text(text)
    idx = args.select
    match = next((c for c in candidates if c.id == idx), None)
    if match is None and 1 <= idx <= len(candidates):
        match = candidates[idx - 1]
    if match is None:
        raise SystemExit(f"No candidate #{idx} found (have {len(candidates)}).")
    return match


def produce(candidate: Candidate, *, do_publish: bool, do_thumbnail: bool, report: Path | None) -> int:
    slug = f"{date.today():%Y-%m-%d}-{_slugify(candidate.hook)}"
    ep = config.episode_dir(slug)
    lines: list[str] = [f"## The Knowles Files — {slug}", "", f"**Story:** {candidate.hook}", ""]

    # Stage 2 — verify (the trust gate).
    fact = verify(candidate.story_and_sources())
    (ep / "factsheet.md").write_text(fact.text, encoding="utf-8")
    if not fact.proceed:
        # Surface the verifier's own reasoning in the comment so the rejection
        # is judgeable without downloading the artifact. Trim to keep it readable.
        reasoning = fact.text.strip()
        if len(reasoning) > 2500:
            reasoning = reasoning[:2500].rstrip() + "\n\n… (truncated — full text in factsheet.md)"
        lines += [
            f"**DO NOT PROCEED** — {fact.reason}", "",
            "A missed week is fine. A false reveal is not. Try `/produce N` with a "
            "different candidate, or `/skip` to close the week.", "",
            "<details><summary>Verifier's reasoning</summary>", "",
            reasoning, "", "</details>",
        ]
        _emit(lines, report)
        print("DO NOT PROCEED — core fact unverified. Stopping.", file=sys.stderr)
        return GATE_EXIT

    # Stage 3 — write.
    script = write(fact.text)
    (ep / "script.txt").write_text(script, encoding="utf-8")
    words = len(script.split())

    # Stage 4 — voice.
    narration, duration = stage4_voice.narrate(script, ep / "narration.wav")

    # Captions, offset by the (trimmed) intro-sting length so they track the
    # narration rather than the music. Timing comes from the actual audio via
    # Whisper (real sync); falls back to proportional if Whisper is unavailable.
    # SRT is a selectable track; the styled ASS (big, left-column) is burned in.
    intro = config.ASSETS / "intro.mp3"
    offset = float(config.cfg("audio", "intro_seconds", default=5)) if intro.exists() else 0.0
    srt = ep / "captions.srt"
    ass = ep / "captions.ass"
    sync_method = captions.build_captions(script, narration, duration, srt, ass, start_offset=offset)

    # Stage 6 — the unique, scroll-stopping NOIR thumbnail (YouTube still).
    concept = stage6_thumbnail.concept_for(script)
    title = concept.video_title or candidate.hook
    thumb: Path | None = None
    thumb_method = "skipped"
    if do_thumbnail:
        thumb, thumb_method = stage6_thumbnail.build_thumbnail(concept, ep / "thumbnail.png")

    # Stage 5 — assemble. The video is the persistent "radio show" visual (a fixed
    # dark image) with the big left-column captions dominant on top. If no radio
    # image is supplied, build_video falls back to this episode's thumbnail.
    mp3 = stage5_assemble.build_audio(narration, ep / "episode.mp3")
    mp4 = stage5_assemble.build_video(mp3, ass, ep / "episode.mp4", background=thumb)

    description = _build_description(candidate)
    meta = {
        "slug": slug, "title": title, "words": words, "duration_sec": round(duration, 1),
        "thumbnail_method": thumb_method, "captions_sync": sync_method, "files": {
            "script": "script.txt", "audio": "episode.mp3", "video": "episode.mp4",
            "captions": "captions.srt", "thumbnail": "thumbnail.png" if thumb else None,
        },
    }

    lines += [f"**Title:** {title}", f"**Length:** ~{words} words / {duration/60:.1f} min",
              f"**Thumbnail:** {thumb_method}", ""]

    # Stage 7 — publish. A publish failure must NOT discard a finished episode:
    # the audio/video/script are already built and saved as artifacts. We catch
    # the error, surface it in the issue comment, and exit with PUBLISH_EXIT so
    # the run stays green and you can fix the upload without re-rendering.
    exit_code = 0
    if do_publish:
        try:
            result = stage7_publish.upload(mp4, title, description, thumb)
            meta["publish"] = {"video_id": result.video_id, "url": result.url,
                               "privacy": result.privacy, "thumbnail_set": result.thumbnail_set}
            lines += [f"**Uploaded ({result.privacy}):** {result.url}",
                      "" if result.thumbnail_set else "_(thumbnail not set — channel may need verification)_"]
            print(result.url)
        except Exception as exc:  # noqa: BLE001 - report any upload failure, keep the episode
            import traceback
            detail = f"{type(exc).__name__}: {exc}"
            meta["publish"] = {"error": detail}
            lines += [
                "**Upload failed — episode was built but not published.**", "",
                f"> {detail}", "",
                f"The finished files are in the run's **knowles-episode** artifact "
                f"(`episodes/{slug}/`). Fix the upload and re-run, or download "
                f"`episode.mp4` and upload it to YouTube by hand.",
            ]
            print("PUBLISH FAILED:\n" + traceback.format_exc(), file=sys.stderr)
            exit_code = PUBLISH_EXIT
    else:
        lines += ["**Publish skipped** (`--no-publish`). Artifacts are in "
                  f"`episodes/{slug}/`."]

    (ep / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # Record the episode so Stage 1 never re-suggests it. Only reached when the
    # story passed the verify gate and was actually built (gate path returns
    # earlier and is intentionally NOT recorded).
    published_url = meta.get("publish", {}).get("url")
    history.record(slug, candidate.hook, title, published_url)

    _emit(lines, report)
    return exit_code


def cmd_produce(args: argparse.Namespace) -> int:
    report = Path(args.report) if args.report else None
    try:
        candidate = _select_candidate(args)
        return produce(candidate, do_publish=not args.no_publish,
                       do_thumbnail=not args.no_thumbnail, report=report)
    except Exception as exc:  # noqa: BLE001 - self-report any crash to the issue comment
        import traceback
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        if report:
            if gemini_client.is_quota_error(exc):
                report.write_text(
                    "**Free Gemini quota exhausted for today.**\n\n"
                    "All configured models hit their free daily request cap, so the "
                    "episode couldn't be built right now. This is a free-tier limit, "
                    "not a fault.\n\n"
                    "Just reply `/produce N` again **after the quota resets** (daily, "
                    "around 00:00 US Pacific). Fewer test runs per day will avoid it. "
                    "To lift the cap entirely, enable billing on the Gemini API project.",
                    encoding="utf-8",
                )
            else:
                report.write_text(
                    "**Production error — the run crashed before finishing.**\n\n"
                    "```\n" + tb[-3500:] + "\n```\n",
                    encoding="utf-8",
                )
        return 1


def cmd_run(args: argparse.Namespace) -> int:
    markdown, candidates = find(exclude=history.recent_hooks())
    print(markdown)
    choice = input("\nPick a candidate (1/2/3, or 'q' to quit): ").strip()
    if choice.lower() in {"q", "quit", ""}:
        print("No pick. Closing the week.")
        return 0
    idx = int(choice)
    candidate = next((c for c in candidates if c.id == idx), candidates[idx - 1])
    return produce(candidate, do_publish=not args.no_publish,
                   do_thumbnail=not args.no_thumbnail, report=None)


def _emit(lines: list[str], report: Path | None) -> None:
    text = "\n".join(lines)
    if report:
        report.write_text(text, encoding="utf-8")
    print("\n" + text, file=sys.stderr)


# --------------------------------------------------------------------------- #
# arg parsing
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="knowles", description="The Knowles Files pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("find", help="Stage 1: find 3 candidate stories")
    f.add_argument("--out", default="candidates.md")
    f.add_argument("--json", default="candidates.json")
    f.set_defaults(func=cmd_find)

    pr = sub.add_parser("produce", help="Stages 2-7 for a chosen candidate")
    src = pr.add_mutually_exclusive_group(required=True)
    src.add_argument("--candidate-file", help="JSON file with a single candidate object")
    src.add_argument("--candidates-file", help="JSON array of candidates (use with --select)")
    src.add_argument("--from-body", help="Text/issue-body file containing the candidates marker")
    pr.add_argument("--select", type=int, default=1, help="Which candidate id/index to produce")
    pr.add_argument("--no-publish", action="store_true")
    pr.add_argument("--no-thumbnail", action="store_true")
    pr.add_argument("--report", help="Write a markdown summary here (for the issue comment)")
    pr.set_defaults(func=cmd_produce)

    r = sub.add_parser("run", help="Local interactive: find + pick + produce")
    r.add_argument("--no-publish", action="store_true")
    r.add_argument("--no-thumbnail", action="store_true")
    r.set_defaults(func=cmd_run)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
