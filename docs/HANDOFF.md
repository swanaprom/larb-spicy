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

YouTube is limiting this internet connection because it was asked too much in a short time (seen 2026-09-28 after ~20 runs and several hundred look-ups in one morning). It's not a program bug, and retrying at once makes it worse.

What the program does about it (since slice 6):
- **It asks YouTube less.** A song (or countdown) already in the cache for this run's mode isn't looked up at all; its length comes from the file. A rerun of a fully cached list makes no YouTube requests. So after a limit, rerunning only asks about the songs that are still missing.
- **It stops instead of retrying.** On the first "not a bot" or HTTP 429 answer, no new look-ups or downloads start; downloads already running finish and stay cached. The run then stops with "YouTube is limiting this connection. Wait a while, then run again; finished songs stay cached.", plus how many songs are already cached. In the window it's the usual pop-up. Nothing is rendered.

What to do: wait (at least an hour, sometimes more), then run again. The program has no cookie option; see [TECH.md](TECH.md) §16, §20.

The ordinary, occasional `HTTP Error 403: Forbidden` is different: it's retried by itself, waiting about 2 s, then 4 s, then 8 s, each a little random so parallel downloads don't retry at the same moment. The waits are `RETRY_BASE_S` / `RETRY_JITTER` at the top of `src/larb/core/pipeline.py` (measured: TECH §20).

## An output named `..._FAILED.mp3` / `.mp4`?

The render finished (or crashed partway), but the result didn't match the plan, so it was **not** given the normal name. The log says why (e.g. `Output is ... s long but should be ... s`). The file is kept only so someone can look at it; don't use it for the event. A file named `....rendering.mp3` / `.mp4` is a run that was interrupted; the next run deletes it by itself.

## Warning: "crossfades next to it shortened"?

A clip too short for the crossfade setting gets shorter crossfades, so the fades never overlap. For a song it means its time range is very short (check the sheet); for the countdown it means the countdown is short for the crossfade setting (the usual countdown, 5.3 s, fits crossfades up to 2.6 s). The run still works.

## Rendering looks wrong but no error?

FFmpeg does **not** fail when a song's end time is past the real length of the video. It quietly makes a broken, out-of-sync file. Song lengths must be checked before rendering (see TECH.md §10). The YouTube metadata length is rounded to whole seconds, so the early check alone is not enough.

## Settings won't save, or won't load?

- Windows refuses to replace `config.toml` while another program has it open (seen as "Access is denied"). Close whatever has it open; the program should retry by itself.
- If you edit `config.toml` in Notepad, a "UTF-8 with BOM" save used to break Python's TOML reader. Reading with `utf-8-sig` fixes it ([TECH.md](TECH.md) §5). Keep that in the code, it is not a typo.
- Comments you type into `config.toml` disappear on the next save. That is normal; the commented reference is `config/example.toml`.

## Something went wrong: where's the log?

Every run writes `workspace/logs/<date>_<time>.log`. It has more than the console: the exact FFmpeg commands, ready to paste into a terminal. Only the 5 newest logs are kept, so copy one somewhere else if you need it later.

## Clearing the download cache

- **In the window:** the **Clear cache** button (bottom row, far from Run). It asks first, with how many files and how much space. Nothing is asked after a run; instead the last line of the log says how much the cache holds.
- **In the terminal:** "Clear the download cache?" is asked after every successful run. Enter means No.

Either way, only the files named by the cache rule above (and leftovers of interrupted downloads) are deleted, nothing else in that folder. Keep the cache while you're still fixing the sheet: the next run won't need to download again.

**Where the cache lives:** leave `cache_directory` empty (it defaults to `workspace/cache/`). Change it only if that disk is nearly full, and then create a **new, empty folder used only by this program**. Never point it at an existing folder like Music or Downloads: clearing works by file-name pattern, so one of your own files that happens to match (e.g. `something_audio.mp3`) would be deleted.

## Running only part of the sheet

Long list? Run it in sections: rows `2-40` today, `41-80` tomorrow (`--rows 2-40` on the command line, or the "from" / "to" fields in the window, where an empty field means "from the first song" or "to the last row": from `41` and an empty "to" runs row 41 to the end). Row numbers are the ones Google Sheets shows on the left; the header is row 1, so the first song is row 2. A single number (`--rows 5`) runs just that row, handy for re-checking one song. Each section is its own output file, and songs already downloaded stay cached between sections.

## Starting it: the window, or the terminal

Use the scripts; they do the environment for you (README, "Quick Start"):

```
run.bat                                                                          (Windows: the window)
run.bat "<sheet URL>" [--rows 2-40] [--countdown <file or URL>] [--verbose]      (Windows: terminal)
./run.sh                                                                         (Linux/Mac: the window)
./run.sh "<sheet URL>" [...]                                                     (Linux/Mac: terminal)
```

Without arguments (e.g. double-clicking `run.bat`) the window opens. On Windows the black
console window starts **minimized** in the taskbar: if something goes wrong before the window
appears, the message is there, and the console waits until you've read it.

`run` checks `.venv` (rebuilds it by itself if it's missing or built with a Python outside the
range), updates yt-dlp, puts `src` on the path, and starts `python -m larb` with your
arguments (none = the window). No need to activate the venv. For the tests: `.venv\Scripts\python.exe -m unittest`
(Linux/Mac: `.venv/bin/python -m unittest`), from the project folder.

## Setup problems?

- **"No Python 3.x to 3.y was found".** Install the version it names (it goes next to any other
  Python; don't uninstall anything), open a **new** terminal, and run `setup_once` again. On
  Windows, `py -0p` lists the Pythons the scripts can see.
- **Linux: "can't build a venv" / "tkinter is missing".** Debian/Ubuntu split these into
  separate packages; setup prints the `sudo apt install ...` line to run. The scripts never run
  `sudo` themselves. If `apt` can't find the Python version (e.g. Ubuntu 26.04 only has 3.14),
  the deadsnakes archive has it (the command is printed too). Ubuntu 24.04 ships Python 3.12,
  which is in the range, so there it isn't needed (tested on a real 24.04 PC, 2026-09).
- **"Couldn't delete the old .venv folder".** Something still uses it: another run window, or a
  terminal/VS Code where it is activated. Close it and run again.
- **Something weird with the venv?** Delete the `.venv` folder and run `setup_once` again. The
  venv is disposable: rebuild, never repair. (It re-downloads FFmpeg, ~200 MB.)
- **Linux: song titles show as boxes in the window.** No font for Thai, Korean or Japanese
  (seen on WSL Ubuntu 26.04, which has none). Setup warns about it and prints the command:
  `sudo apt install fonts-thai-tlwg fonts-noto-cjk` (Fedora: `sudo dnf install
  google-noto-sans-thai-fonts google-noto-sans-cjk-fonts`). Then restart the window. Windows
  and Mac already have these fonts.
- **FFmpeg.** Setup downloads it into `.venv` (static-ffmpeg). If that fails, a system FFmpeg
  7.1 or newer is used; otherwise setup offers to install one. A run never downloads FFmpeg.

## "Open file" says "No app is set to open .mp4 files"?

No app on this computer is set to open `.mp4` / `.mp3` files (seen on a fresh Ubuntu, which has
no video player). Install a player (e.g. VLC) and try again, or use **Open folder**. The window
shows this in a pop-up, with the system's own reason in brackets, and logs it as a warning.
Open folder failing works the same way (no file manager set).

On Linux and Mac the program waits up to 30 s for `xdg-open` / `open` to report; if it's still
running then, it's showing something, so that counts as success.

## Updating Python (every few years)

yt-dlp drops Python versions once they reach end of life; when `run` warns that yt-dlp can't
be updated even though the internet works, or setup can't install it, this is the likely cause.

1. Install the new Python **alongside** the old one; don't uninstall anything yet.
2. Change the range in `python-range.txt` (e.g. `3.12-3.14`).
3. Delete the `.venv` folder and run `setup_once`: it builds the venv with the newest Python in
   the range. (Without deleting, it keeps a venv whose Python is still in the range.)
4. Run the tests. Pass → commit and tag a new CalVer release; only then uninstall the old
   Python. Fail → usually a pinned library needs bumping; hand the error to an AI.

## Stopping a run

In the window, Run turns into **Stop** during a run (it asks first). Stopping can take a few
seconds: a YouTube look-up that has already started is allowed to finish, while downloads and
rendering stop at once. Songs already downloaded stay in the cache; half-finished downloads are
deleted; nothing unfinished gets the normal output name (anything already written becomes
`..._FAILED`). Closing the window during a run offers the same stop, then closes.

## Countdown from YouTube

The countdown can be a YouTube link (`--countdown <URL>`, or `countdown.default_urls` in `config.toml`). It's downloaded and cached like a song. In `config.toml`, put the link in quotes: `default_urls = ["https://www.youtube.com/watch?v=..."]`. Without quotes the file doesn't load.

## What are recommended upgrades?

- **Intro clip:** an optional clip at the very start, before the first countdown (e.g. a "*Boom* Open the floor" opener). In the window: an on/off choice, plus a field for a YouTube link or file, like the countdown's; the field is greyed out when off. On by default, with the group's intro as the default (like `countdown.default_urls`). It would be cached, normalised and crossfaded like the countdown, and never mirrored.
- Expose some configs in TOML as 'Advanced Settings' into GUI, currently hide by design to keep it direct and minimal.
- **Est. Length:** show the planned output length before running. The button is already in the window, disabled ("Coming later"). The core already calculates the length when it plans the render; the work is to get it earlier: an **estimate** is possible right after the YouTube look-ups (YouTube's lengths are rounded to whole seconds), and it's **exact** only after the downloads, when the real files have been measured.
- **Remember the last inputs** (sheet link, countdown) between sessions, in their own small memory file, separate from `config.toml` (which holds settings, not what one run used).
- **The accent colours as a file-only config**, so a future generation can restyle the window without touching code. Today they are the constants at the top of `src/larb/gui/theme.py`.
- Remember each video's length between runs. Since slice 6, a song already **cached for this mode** isn't looked up (its length comes from the file). Songs not downloaded yet, or cached only in the other mode, are still looked up on every run, e.g. while the sheet is being fixed before the first full run. Saving looked-up lengths (e.g. next to the cache) would skip those too, which is what gets a connection limited ("Sign in to confirm you're not a bot", HTTP 429).
- Support YouTube cookies (yt-dlp's `--cookies-from-browser`), the usual cure for the bot check. Trade-off: the program then uses a logged-in account's session. Downloads count against that account, and a heavy run could get the account itself limited or flagged, so it should be a throwaway account, never someone's personal one. Not supported for now (maintainer decision 2026-09-28); until then, wait and retry.
- Notification: Error/Success have different noise. and also the notification thing that make icon in taskbar blink orange.
- Redundant song inspector button: match pattern as much as possible eg., same song and artist, same videoID, still not as clear as throwing CSV to AI but could help a bit. (Song name and URL is a clear flag, the artist and song with likely similiar name but not exact is ambigous). Everything flag by this will just be report and log as warning, not error. (Or even better, also the pop up report + log).