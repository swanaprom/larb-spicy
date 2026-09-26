# Hand-off Notes

Gotchas for the next maintainer. Details and evidence live in [TECH.md](TECH.md).

## Downloads failing?

1. Update yt-dlp first (`pip install -U yt-dlp` inside the venv).
2. Still failing? It may need a JS runtime. As of 2026-09-26, YouTube downloads worked **without** one, but yt-dlp already warns that this is deprecated. yt-dlp only uses **Deno** by default. Node.js being installed does nothing unless `--js-runtimes node` is passed. Installing Deno is the likely fix.

## Rendering looks wrong but no error?

FFmpeg does **not** fail when a song's end time is past the real length of the video. It quietly makes a broken, out-of-sync file. Song lengths must be checked before rendering (see TECH.md §10).
