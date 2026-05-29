# The Knowles Files — Production Engine

A weekly true-story show, produced end-to-end on **free infrastructure** and
uploaded straight to **YouTube**. You make two clicks a week: pick a story, then
flip the finished private video to public after a glance.

This repo is the automation around the show bible in
[`KNOWLES_FILES.md`](KNOWLES_FILES.md). The locked identity, the six-part episode
skeleton, the frozen voice — all of it lives in code so a weekly run can't drift.

---

## How it maps to the spec

| Spec stage | Here | Free tool |
|------------|------|-----------|
| 1 · Find | `stage1_find.py` | Gemini + Google Search grounding |
| 2 · Verify (the trust gate) | `stage2_verify.py` | Gemini + Search grounding |
| 3 · Write | `stage3_write.py` | Gemini |
| 4 · Voice (Alnilam) | `stage4_voice.py` | Gemini TTS |
| 5 · Assemble (MP3 + MP4 + captions) | `stage5_assemble.py`, `captions.py` | ffmpeg |
| 6 · Thumbnail | `stage6_thumbnail.py` | Gemini image (Nano Banana) + Pillow fallback |
| 7 · Publish | `stage7_publish.py` | YouTube Data API v3 |
| Orchestration / scheduling | `.github/workflows/` | GitHub Actions |

**Human-in-the-loop** stays exactly where the spec wants it: the 30-second story
pick (a `/produce N` reply), the thumbnail glance, and the final publish (videos
upload **private** by default).

---

## Free infrastructure used

- **Google AI Studio (Gemini API)** — free tier covers text, Search grounding and
  TTS. Get a key: <https://aistudio.google.com/apikey>. *(Image generation / Nano
  Banana may require billing on your account; if so the pipeline falls back to a
  local Pillow thumbnail at no cost.)*
- **YouTube Data API v3** — free; ~1,600 quota units per upload against a
  10,000/day budget. Plenty for weekly.
- **GitHub Actions** — free (unlimited minutes on public repos; 2,000 min/month
  private). Runs the whole thing and installs ffmpeg for you.
- **ffmpeg** — free, pre-available on the runner.

---

## One-time setup

### 1. Secrets (repo → Settings → Secrets and variables → Actions)

| Secret | What |
|--------|------|
| `GEMINI_API_KEY` | Your Google AI Studio key |
| `YOUTUBE_TOKEN_JSON` | The contents of `token.json` from the step below |

Optional **repository variables** (same screen, "Variables" tab):

| Variable | Default | Meaning |
|----------|---------|---------|
| `KNOWLES_PRIVACY` | `private` | `private` \| `unlisted` \| `public` |
| `KNOWLES_PUBLISH_AT` | _(unset)_ | ISO8601, e.g. `2026-06-01T18:00:00Z` — schedule going public |

### 2. YouTube authorization (run once on your machine)

1. Google Cloud Console → enable **YouTube Data API v3**.
2. Create an **OAuth client → Desktop app**, download as `client_secret.json` into
   this folder.
3. `pip install -r requirements.txt`
4. `python scripts/auth_youtube.py` → approve in the browser → it writes
   `token.json` and prints a one-line version.
5. Paste that line into the `YOUTUBE_TOKEN_JSON` secret.

> `client_secret.json` and `token.json` are git-ignored. Never commit them.

### 3. Assets (optional, recommended)

See [`assets/README.md`](assets/README.md). At minimum, add
`assets/knowles_portrait.png` so every thumbnail shows the same face. Music and a
background image are optional — the pipeline runs without them.

---

## The format: "Real or Rubbish?"

Every episode tells one story that is **either true or completely fabricated**, and
the audience has to decide which, research it, and post their verdict in the
comments. The video **never says** which it is — the honest answer is revealed at
the **start of next week's episode**. Two rules keep it trustworthy:

- Real stories still pass the **verify gate** (2+ independent credible sources).
- No story ever names a real company or person, so a fabricated tale can't defame
  anyone — and real vs fake look identical, which is the whole game.

The integrity promise shifts from "every story is true" to **"the answer is always
honest"**: real ones are genuinely verified, fakes are clearly a game, and the
truth always lands the following week.

## The weekly run (GitHub Actions)

1. **Monday 09:00 UTC** the *Find candidates* workflow runs (or trigger it
   manually under the Actions tab) and opens an **issue** with 3 true stories.
2. You read it (~30 s) and either:
   - reply **`/produce 2`** to make true story #2 this week's episode, or
   - reply **`/produce fake`** to run a fabricated episode instead, or
   - reply `/skip` to close the week.
3. The *Produce episode* workflow writes, voices, assembles (radio-show visual +
   big captions), makes the noir thumbnail, and uploads the video **private** —
   then comments the link back. The episode opens by revealing **last week's**
   verdict. A real story that fails the verify gate comments **DO NOT PROCEED**.
4. You open the link, glance, and hit Publish on YouTube. Done.

You control the real/fake mix (the audience never knows which you picked). The
ledger (`produced.json`) remembers each episode's verdict so next week can reveal it.

---

## Running locally

Needs Python 3.11+ and ffmpeg on PATH.

```bash
pip install -r requirements.txt
cp .env.example .env            # fill in GEMINI_API_KEY (and keep token.json nearby)

# Interactive: find, pick at the prompt, produce. Skip the upload while testing:
python -m knowles.pipeline run --no-publish

# Or step through:
python -m knowles.pipeline find                       # writes candidates.md / .json
python -m knowles.pipeline produce --candidates-file candidates.json --select 2 --no-publish
```

Outputs land in `episodes/<date>-<slug>/`: `script.txt`, `narration.wav`,
`episode.mp3`, `episode.mp4`, `captions.srt`, `thumbnail.png`, `factsheet.md`,
`meta.json`.

---

## Layout

```
knowles/            pipeline package (one module per stage)
scripts/            auth_youtube.py (one-time OAuth)
assets/             portrait, intro/outro music, background (git-ignored binaries)
episodes/           generated output (git-ignored)
.github/workflows/  find.yml (cron → issue), produce.yml (/produce N → stages 2-7)
config.yaml         tunables (models, voice, video, publish)
KNOWLES_FILES.md    the show bible
```

## Notes & limits

- Gemini free tier is rate-limited; the client retries 429s with backoff. A weekly
  cadence sits comfortably inside the free quotas.
- Custom thumbnails require a verified YouTube channel. If yours isn't verified
  yet, the video still uploads; only the thumbnail set is skipped.
- Nothing here defeats YouTube's own policies — keep the reveal true. That's the
  whole show.
