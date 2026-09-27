# Hand-off Notes

Gotchas for the next maintainer. Details and evidence live in [TECH.md](TECH.md).

## Downloads failing?

1. Update yt-dlp first (`pip install -U yt-dlp` inside the venv).
2. Still failing? (Especially 403 Error) It may need a JS runtime. As of 2026-09-26, YouTube downloads worked **without** one, but yt-dlp already warns that this is deprecated. yt-dlp only uses **Deno** by default. Node.js being installed does nothing unless `--js-runtimes node` is passed. Installing Deno is the likely fix. Node.js also works (tested 2026-09-26) if yt-dlp is told to use it: `--js-runtimes node`.

## One specific song always error downloading?

There's a hack: 
- Download them manually, and put it in cache folder.
- Rename the downloaded file to match the naming convention.
- Once the batch begin again, it will count as a cached song and skip the download.
- It should likely get include into the output eventually.

## Rendering looks wrong but no error?

FFmpeg does **not** fail when a song's end time is past the real length of the video. It quietly makes a broken, out-of-sync file. Song lengths must be checked before rendering (see TECH.md §10). The YouTube metadata length is rounded to whole seconds, so the early check alone is not enough.

## Settings won't save, or won't load?

- Windows refuses to replace `config.toml` while another program has it open (seen as "Access is denied"). Close whatever has it open; the program should retry by itself.
- If you edit `config.toml` in Notepad, a "UTF-8 with BOM" save used to break Python's TOML reader. Reading with `utf-8-sig` fixes it ([[TECH.md]] §5). Keep that in the code, it is not a typo.
- Comments you type into `config.toml` disappear on the next save. That is normal; the commented reference is `config/example.toml`.

## What are recommended upgrades?

- Expose some configs in TOML as 'Advanced Settings' into GUI, currently hide by design to keep it direct and minimal.
