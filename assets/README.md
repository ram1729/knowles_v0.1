# Assets

Drop the show's fixed media here. Everything is **optional** — the pipeline
degrades gracefully — but supplying these gives you the full house style.

| File | Used by | If missing |
|------|---------|------------|
| `knowles_portrait.png` | Thumbnail (Nano Banana reference, keeps his face identical) | Thumbnail falls back to a local Pillow composite over a dark card |
| `intro.mp3` | Prepended to every episode's audio | Skipped |
| `outro.mp3` | Appended to every episode's audio | Skipped |
| `background.png` | Static visual behind the captions in the MP4 (1920×1080) | Solid dark colour from `config.yaml` |

These four binaries are git-ignored so the repo stays light and you don't commit
copyrighted music. Commit them only if you have the rights and want them in CI —
otherwise the GitHub Actions runner uses the graceful fallbacks above.

**Music:** use royalty-free / CC0 tracks (e.g. your own, or a free library you've
cleared). Keep them short — a few seconds of intro sting, a few of outro.

**Portrait:** a single clean, front-facing portrait of Gregory Knowles. Generate
it once (any tool), save it here as `knowles_portrait.png`, and never change it —
its sameness is what makes every thumbnail recognisably him.
