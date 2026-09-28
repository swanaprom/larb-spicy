# Hand-off Notes

Gotchas for the next maintainer. Details and evidence live in [TECH.md](https://claude.ai/chat/TECH.md).

## Downloads failing?

1. Update yt-dlp first (`pip install -U yt-dlp` inside the venv).
2. Still failing? (Especially 403 Error) It may need a JS runtime. As of 2026-09-26, YouTube downloads worked **without** one, but yt-dlp already warns that this is deprecated. yt-dlp only uses **Deno** by default. Node.js being installed does nothing unless `--js-runtimes node` is passed. Installing Deno is the likely fix. Node.js also works (tested 2026-09-26) if yt-dlp is told to use it: `--js-runtimes node`.

## One specific song always error downloading?

There's a hack:

- Download them manually, and put it in cache folder.
- Rename the downloaded file to match the naming convention.
- Once the batch begin again, it will count as a cached song and skip the download.
- It should likely get include into the output eventually.

**Naming convention for cached files:** `<videoID>_<kind>.<ext>`

- `<videoID>` is the 11-character ID from the YouTube link, exactly as written (case matters). For `https://www.youtube.com/watch?v=oKBwWQI-IoI` or `https://youtu.be/oKBwWQI-IoI?si=...`, it's `oKBwWQI-IoI`.
- `<kind>` is `audio` for audio-only runs, or `v` plus the `max_height` setting for video runs, e.g. `v720`. Use the **setting's** number, even if the file you downloaded is smaller (e.g. only 480p exists: still `v720`).
- `<ext>` is the file's own extension; don't rename it (`.mp4`, `.m4a`, `.webm`, `.mp3`, …).
- Examples: `oKBwWQI-IoI_audio.m4a`, `oKBwWQI-IoI_v720.mp4`.
- The song title and artist are **not** in the name, so fixing a typo in the sheet doesn't cause a re-download. Titles show up in the log instead.
- An audio-only file doesn't count for a video run, and the other way round, because the `<kind>` part differs.

## Each video is looked up once — keep `process=False`

While checking the sheet, the yt-dlp adapter looks each video up and remembers the answer; the download then reuses it instead of asking YouTube again (~1.5 s saved per song). This only works because the look-up asks yt-dlp for the **raw** info (`extract_info(..., process=False)`). Info that yt-dlp has already "processed" (formats picked) failed with `HTTP Error 403` on every audio download tried when reused. So don't "simplify" the look-up back to a plain `extract_info(url, download=False)`. Details: [TECH.md](TECH.md) §14.

If a reused look-up fails anyway, the adapter looks the video up again by itself and logs `... looking it up again`. That line is normal now and then (YouTube's intermittent 403), not a bug.

## "Sign in to confirm you're not a bot" or "HTTP Error 429: Too Many Requests"?

YouTube is limiting this internet connection because it was asked too much in a short time (seen 2026-09-28 after ~20 runs and several hundred look-ups in one morning). It's not a program bug, and retrying at once makes it worse. Wait (at least an hour) and run again. The program has no cookie option; see [TECH.md](TECH.md) §16.

## An output named `..._FAILED.mp3` / `.mp4`?

The render finished (or crashed partway), but the result didn't match the plan, so it was **not** given the normal name. The log says why (e.g. `Output is ... s long but should be ... s`). The file is kept only so someone can look at it; don't use it for the event. A file named `....rendering.mp3` / `.mp4` is a run that was interrupted; the next run deletes it by itself.

## Warning: "crossfades next to it shortened"?

A clip too short for the crossfade setting gets shorter crossfades, so the fades never overlap. For a song it means its time range is very short (check the sheet); for the countdown it means the countdown is short for the crossfade setting (the usual countdown, 5.3 s, fits crossfades up to 2.6 s). The run still works.

## Rendering looks wrong but no error?

FFmpeg does **not** fail when a song's end time is past the real length of the video. It quietly makes a broken, out-of-sync file. Song lengths must be checked before rendering (see TECH.md §10). The YouTube metadata length is rounded to whole seconds, so the early check alone is not enough.

## Settings won't save, or won't load?

- Windows refuses to replace `config.toml` while another program has it open (seen as "Access is denied"). Close whatever has it open; the program should retry by itself.
- If you edit `config.toml` in Notepad, a "UTF-8 with BOM" save used to break Python's TOML reader. Reading with `utf-8-sig` fixes it ([TECH.md](https://claude.ai/chat/TECH.md) §5). Keep that in the code, it is not a typo.
- Comments you type into `config.toml` disappear on the next save. That is normal; the commented reference is `config/example.toml`.

## Something went wrong: where's the log?

Every run writes `workspace/logs/<date>_<time>.log`. It has more than the console: the exact FFmpeg commands, ready to paste into a terminal. Only the 5 newest logs are kept, so copy one somewhere else if you need it later.

## "Clear the download cache?"

Asked after every successful run. Enter means No. Yes deletes only the files named by the cache rule above (and leftovers of interrupted downloads), nothing else in that folder. Say No while you're still fixing the sheet: the next run won't need to download again.

**Where the cache lives:** leave `cache_directory` empty (it defaults to `workspace/cache/`). Change it only if that disk is nearly full, and then create a **new, empty folder used only by this program**. Never point it at an existing folder like Music or Downloads: clearing works by file-name pattern, so one of your own files that happens to match (e.g. `something_audio.mp3`) would be deleted.

## Running only part of the sheet

Long list? Run it in sections: rows `2-40` today, `41-80` tomorrow (`--rows 2-40` on the command line, or the row fields in the GUI). Row numbers are the ones Google Sheets shows on the left; the header is row 1, so the first song is row 2. A single number (`--rows 5`) runs just that row, handy for re-checking one song. Each section is its own output file, and songs already downloaded stay cached between sections.

## Running it from a terminal

From the project folder, in VS Code's terminal (PowerShell):

```
.venv\Scripts\Activate.ps1
$env:PYTHONPATH="src"
python -m larb "<sheet URL>"
```

(In the old Command Prompt, the middle line is `set PYTHONPATH=src`; on Linux/Mac, `source .venv/bin/activate` and `export PYTHONPATH=src`.) The setup scripts will replace these steps once they exist.

## Countdown from YouTube

The countdown can be a YouTube link (`--countdown <URL>`, or `countdown.default_urls` in `config.toml`). It's downloaded and cached like a song. In `config.toml`, put the link in quotes: `default_urls = ["https://www.youtube.com/watch?v=..."]`. Without quotes the file doesn't load.

## What are recommended upgrades?

- Expose some configs in TOML as 'Advanced Settings' into GUI, currently hide by design to keep it direct and minimal.