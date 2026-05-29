# Assets

Drop the show's fixed media here. Everything is **optional** — the pipeline
degrades gracefully — but supplying these gives you the full house style.

| File | Used by | If missing |
|------|---------|------------|
| `radio_bg.png` | **The persistent "radio show" video background** (1920×1080) shown for the whole episode under the big captions | Falls back to the episode's thumbnail, then a solid dark colour |
| `knowles_portrait.png` | Thumbnail — his face. Hybrid engine cuts him out and composites onto a free AI scene | Thumbnail falls back to a dark card with title text |
| `knowles_cutout.png` *(optional)* | A pre-made **transparent** PNG of just Gregory. If present, the hybrid thumbnail skips background-removal entirely (faster, no rembg) | Background-removal runs on `knowles_portrait.png` automatically |
| `intro.mp3` | First few seconds prepended to every episode's audio | Skipped |
| `outro.mp3` | First few seconds appended to every episode's audio | Skipped |
| `background.png` *(legacy)* | Only used if `video.background_mode: episode/color` and no radio image | Solid dark colour from `config.yaml` |

### Making `radio_bg.png` (the on-air video background)

This is the calm, dark image the viewer sees for the whole episode while Gregory
talks — the **big captions sit on the left**, so keep that side simple/empty and
put any subject on the **right**. The pipeline darkens it further automatically,
so it stays non-distracting. Make it once, reuse forever. Suggested prompt:

```
A moody film-noir radio studio at night, 16:9, very dark and atmospheric. An
"ON AIR" sign glowing warm amber, a vintage broadcast microphone and a hint of
a cab-driver's cap and tweed on the RIGHT side, deep shadows, single warm key
light, heavy desaturation, cinematic grain. The entire LEFT HALF is dark, empty
negative space (no objects, no text) reserved for large captions. No text,
no watermark, no faces in close-up. Calm, classy, understated.
```

Save the result as `assets/radio_bg.png` and upload it like the others. Tune how
dark it gets with `video.scrim_global` / `video.caption_panel` in `config.yaml`.

### Making `knowles_cutout.png` once (optional, recommended)

The hybrid thumbnail needs Gregory on a transparent background. CI removes the
background automatically with `rembg`, but you can make a clean cutout once so
every run is fast and dependency-free. Run this in a Colab cell after uploading
`knowles_portrait.png`:

```python
!pip install -q rembg onnxruntime pillow
from rembg import remove
from PIL import Image
remove(Image.open("knowles_portrait.png").convert("RGBA")).save("knowles_cutout.png")
print("saved knowles_cutout.png — upload it to the repo's assets/ folder")
```

Then upload the resulting `knowles_cutout.png` to `assets/` (same way as the
portrait). For the cleanest cutout, use a portrait with a plain background.

These four binaries are git-ignored so the repo stays light and you don't commit
copyrighted music. Commit them only if you have the rights and want them in CI —
otherwise the GitHub Actions runner uses the graceful fallbacks above.

**Music:** use royalty-free / CC0 tracks (e.g. your own, or a free library you've
cleared). Keep them short — a few seconds of intro sting, a few of outro.

**Portrait:** a single clean, front-facing portrait of Gregory Knowles. Generate
it once (any tool), save it here as `knowles_portrait.png`, and never change it —
its sameness is what makes every thumbnail recognisably him.
