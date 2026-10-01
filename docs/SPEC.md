**Version:** 2026.2 (CalVer: `<year>.<index_of_versions_in_same_year>`)

> This doc is written to survive months-long gaps and generational hand-off. If something feels obvious right now, write it down anyway — it won't be obvious in six weeks or to the next maintainer.

---

## 1. Purpose & Scope

- **In scope (2026.1):** Random Dance combiner batch. It will download a list of Youtube videos, only in corresponding time range, and combine into 1 long video/audio with countdowns in between. Can run on both Windows, Linux, and possibly Mac.
- **Out of scope:** Google Sheet access-control enforcement (documented as an operator responsibility — see [[#9. Pipeline Stages (detailed)]]).

## 2. Goals (ranked)

When goals conflict, the order decides.

1. **Reliability** — pipeline fails loudly and specifically, never silently produces a bad combination.
2. **Maintainability** — next maintainer (possibly with little Python experience) can read this doc + code and make a small change safely.
3. **Efficiency** — faster than the `moviepy` prototype. Baseline (2026-09, i5-6400, same 5 songs, 720p video): prototype 605 s, this pipeline 104 s end to end, about 5.8× faster, at higher quality. Target: don't regress below this baseline. Details in TECH §10.

## 3. Non-Goals

Explicit "we are not doing this, and here's why" — this is what stops scope creep from a future maintainer who tries to be helpful.

- Not enforcing Google Sheet sharing/visibility settings (operator's job — document the checklist in the README, don't code around human error).
- Not downloading only the needed segment. Full-song download + trim during render is the deliberate choice: confirmed in the 2026-09 spike to be both exact and fastest (segment download starts several seconds early, and forcing it to be exact is several times slower than a full download). Full songs are also reusable from the cache.
- Not doing the OS-specific releases. Learning curve is flat, Maintainers can rely on AI reading README and follow straight forward instruction. Distribution is clone + setup scripts instead (§16). A frozen executable (e.g. PyInstaller) would also freeze yt-dlp inside it, and an outdated yt-dlp is exactly what breaks when YouTube changes. It would also need per-OS builds and trigger antivirus / "unidentified developer" warnings.
- Not using `make`. Windows doesn't ship it, and the most likely successor is on Windows.

## 4. Glossary

Keep this current — a future non-technical maintainer will live here.

|Term|Meaning|
|---|---|
|Manifest|The parsed, validated table derived from the Google Sheet, used to drive the pipeline|
|Countdown|Intro video/audio clip inserted before each song|
|Cache|Previously-downloaded media kept on disk, named by video ID and type (e.g. `abc123_audio`, `abc123_v720`), so reruns and interrupted runs don't download again (§10)|
|Row error|A row that can't be used safely and is skipped, with a reported reason (e.g. unavailable video, bad or out-of-range time range, download still failing after retries)|
|Row warning|A row with a non-critical issue (e.g. missing artist) that still runs|
|Chunk|A group of 6 songs rendered as one piece of video; chunks are joined in the middle of a countdown without re-encoding, so memory stays low for any list length|
|Padding|Each song is taken 1 s earlier and 1 s later than its sheet time range (clamped to the song's real start/end), so the crossfade doesn't eat into the part the dancers need|
|File-only setting|A config key that exists only in `config.toml` and is never shown in the GUI. For maintainers who have re-tested a change, not for operators (§7)|
|Peak normalization|Each clip's loudest point is raised or lowered to the same level (−1 dBFS), so quiet countdowns and loud songs sit together without flattening the music|

## 5. Architecture Overview

The operator window (layout, behavior, colours) is specified in [GUI.md](GUI.md). This section covers how the parts fit together.

A short narrative + a diagram (even ASCII) beats prose alone here, since this is the thing that decays fastest in your memory between sessions.

```
[setup_once] --> [run] --> [GUI / CLI]

[GUI / CLI] --(sheet URL, countdown, settings edits)--> [Core]

Core (standard library only: rules, orchestration, decisions)
  ├─ manifest rules (§8), mirror rule, padding, peak gain
  ├─ cache key + cache check (§10)
  ├─ parallel downloads + retries
  └─ talks to the outside world ONLY through five ports:

  Port              What the core asks for                    Adapter (today)
  ───────────────   ───────────────────────────────────────   ─────────────────────────
  SettingsStore     load / save settings                      TOML file (tomllib + tomli-w)
  SongListSource    rows of the song list                     Google Sheet CSV export / local CSV
  MediaSource       look up a video's info · download it      yt-dlp
  MediaProcessor    measure a clip · render the compilation   FFmpeg (the one FFmpeg helper lives here)
  EventSink         report progress, warnings, errors         console, log file, GUI window
```

Adapters are connected to ports in exactly one place, `src/larb/app.py`, used by both the terminal version and the GUI. Adapters can be replaced without touching the core, as long as the port stays the same. Port signatures change only with the maintainer's approval (CLAUDE.md).

**Module boundary rule (maintainability keystone):** the GUI never touches yt-dlp/FFmpeg directly, and the core never imports GUI code. If you can't unit-test a core module without spinning up the GUI, the boundary has leaked.

**Concurrency model:** settings loaded once at pipeline start (you already decided this — restate it here so it doesn't get "fixed" by someone who reads only the GUI code and assumes live reloading is a bug).

## 6. Tech Stack

|Concern|Choice|Notes / alternatives considered|
|---|---|---|
|Language|Python 3.11–3.13 (tested range)|Pinned as a range, not loose: the venv can't upgrade its own Python, and a new Python can break pinned libraries. 3.11 is also the floor for `tomllib`. Range lives in one file read by both scripts (§16)|
|Video/audio download|`yt-dlp` (always latest, not pinned)|replaces `moviepy` download path from prototype. The only unpinned dependency — see §16|
|FFmpeg binary|pip-bundled binary (`static-ffmpeg`), **FFmpeg 7.1 or newer**|Lives in the venv, pinned with it, no admin rights needed. Fallback: a system FFmpeg, if it's 7.1 or newer; else prompt the operator to install one. Why 7.1: long song lists need an option only 7.1+ has, and one version rule means one tested code path. An older FFmpeg stops the run with a clear "too old" message|
|JS runtime (Deno / Node)|**Not required** — add only if yt-dlp actually breaks without one|2026-09 spike: downloads work without one (yt-dlp prints a deprecation warning). Node also works if passed explicitly. If it ever becomes necessary, same handling as system-bound FFmpeg (check + ask). Note kept in HANDOFF.md|
|Trim / mirror / crossfade|FFmpeg via `subprocess`, through one internal helper module. **Audio: one pass. Video: chunks of 6 songs (hard-coded), joined**|Helper owns every FFmpeg call, keeps binary path separate from the argument list. One pass gives exact lengths and A/V sync, but for video it opens every song at once and needs about 0.5 GB of memory per song (measured 2026-09), so it fails after ~6–8 songs on a low-mid PC. Chunking with the tested hybrid method (TECH §10) keeps memory flat for any list length; used always, so there is one code path. Measured 2026-09: a 71-song video peaked under 1 GB; with the audio pass running alongside the video chunks, a 3-song render is about 3% slower than one pass. 6 songs per chunk leaves room for 60 fps sources or a higher `max_height`. Audio one pass used 0.32 GB for 71 songs|
|GUI framework|Tkinter (`ttk`)|Zero dependencies (nothing to pin, nothing that can vanish from PyPI), most examples for AI-assisted successors, and enough styling (colors, fonts, log tags) for the actual UI. Rejected: Qt/PySide6 (heavy + licensing questions), CustomTkinter (third-party, risks lagging a Python bump), PySimpleGUI (now needs a license key). Fixed dark theme with one accent colour: plain Tkinter doesn't follow the system's light/dark setting without extra work. Design: [GUI.md](GUI.md)|
|Config format|TOML — `tomllib` (read, 3.11+) + `tomli-w` (write, pinned)|Python has no built-in TOML writer. But align best among the goals.|
|Sheet access|Public CSV export URL + standard library (`csv`)|No credentials to inherit or expire, no Google Cloud console for a successor, already tested including the special-character/encoding fix. Matches the §3 non-goal on sharing settings. Local CSV file stays as fallback (§9 stage 2). Rejected API + service account: only buys private-sheet reads and write-back, neither needed. Revisit if writing back to the sheet is ever wanted|
|Packaging|Clone repo + `setup_once` / `run` scripts (`.bat` for Windows, `.sh` for Linux/Mac)|Plain `python -m venv` + `requirements.txt` with exact `==` pins. No extra tools needed beyond Python itself. Rejected: PyInstaller releases, `make` (see §3)|

## 7. Configuration Schema (TOML)

Write the actual schema, not just "it's configurable." This is the contract between GUI and core.

The live file is `config/config.toml` (gitignored). On first run it's created from `config/example.toml`, comments included. It deliberately does **not** live in `workspace/`, since that folder gets deleted to free space and settings shouldn't go with it.

Keys marked **file-only** are never shown in the GUI. They hold values chosen by testing (see TECH.md); change them only after re-testing.

```toml
[output]
directory = ""           # empty = workspace/output/. The operator may choose any folder.
filename_template = ""   # empty = {date}_{time}. Only {date} and {time} are allowed (no event name:
                         # ordering by time is enough and keeps the GUI uncramped). No extension:
                         # the program appends .mp4 or .mp3. Never overwrites an existing file.

[countdown]
default_urls = ["https://www.youtube.com/watch?v=<VIDEO_ID>"]
                         # YouTube links, in quotes. The first entry is used. The template ships with the
                         # group's standard countdown; the real link lives in config/example.toml.
default_files = []       # local files; the first entry is used if there's no URL.
# Countdown choice: the run's countdown (GUI field / --countdown) → default_urls[0] → default_files[0] → stop with a message.

[download]
cache_directory = ""     # empty = workspace/cache/. Change only if that disk is nearly full, and then
                         # point it at a NEW, EMPTY folder used only by this program (never an existing
                         # folder with other files: clearing the cache deletes files by name pattern, §10).
max_parallel_downloads = 3   # file-only. Tested best for video; more is slower on a full connection (TECH §9)
max_retries = 2              # file-only. Retries per song, for both look-ups and downloads, before it becomes a row error (TECH §9)
max_parallel_lookups = 5     # file-only. YouTube checks at once while building the manifest. Separate from downloads:
                             # look-ups wait on YouTube, not bandwidth, so more at once helps (measured 2026-09)
max_height = 720             # file-only. Largest video height to download, in pixels (720 = "720p").
                             # Also the output height: output is never taller than this. Even number, 144–4320.
# Codec preference when downloading (prefer H.264) is hard-coded in the downloader adapter:
# it depends on what each download tool can do, and H.264 is also much faster to render (TECH §9).
# TODO: timeout — yt-dlp has its own network timeout/retry options; decide in the downloader slice whether they're enough.

[processing]
audio_only = true
mirror = false                   # two modes, see §8 "Mirror rule"
crossfade_duration_seconds = 0.8 # above 0, at most 10. The MOST each join uses: a join next to a short
                                 # clip gets less, with a warning (§9 stage 6). No "no crossfade" option by design.
                                 # Default 0.8. In the GUI, input that isn't a number restores the default.
# Deliberately NOT configurable (hard-coded):
# - Audio normalization: always on, peak to −1 dBFS (§9).
# - Output video format: H.264, standard 4:2:0 color, 30 fps, height = download.max_height.
#   H.264 in this form is the only format guaranteed to play in Windows' built-in players
#   without extra installs (the spike found a 4:4:4 variant that won't play, TECH §10).
# - Audio-only output: .mp3.

[sheet.columns]
# file-only. Maps each field to the sheet's column HEADER NAME (not position), so inserting
# or reordering columns doesn't break parsing. A header that isn't found aborts the run, naming it.
# Only the sheet adapter uses this, to turn rows into manifest fields; the core never sees column names.
song_title = "ชื่อเพลง"
artist     = "ศิลปิน"
url        = "URLs"
time_range = "ช่วงเวลา"
mirrored   = "Mirrored แล้ว"
```

**Read rule:** GUI requests settings detail from core program ONLY on open to resume the change.

**Write rule (revised):** GUI edits live in memory. On blur/enter the core validates the field and pings the corrected value back to the GUI (e.g. clipping an out-of-bound value), but does **not** write to disk. The whole config is validated and written **once, when Run is hit** — which doubles as a whole-settings consistency check before every run. Write is atomic (temp file + rename).

- Consequence: edits are lost if the GUI is closed without running → also save (or prompt) on close.
- TODO: still document per-field validation behavior — non-existent directory: clamp, reject, or warn?

## 8. Manifest Schema & Validation Rules

This is the section most likely to save you future debugging time — write the rule table now while it's fresh.

Current sheet layout (2026-09), in order: `ชื่อเพลง` (song title), `ศิลปิน` (artist), `URLs`, `ช่วงเวลา` (time range, one column, e.g. `0:27-1:04`), `ผู้เสนอเพลง + ชั้นปี` (proposer), `Mirrored แล้ว` (already mirrored), `หมายเหตุ` (notes). Columns are found by header name through `[sheet.columns]` (§7). Changing which columns exist is a schema change (see CLAUDE.md).

|Column|Required?|Validation|On failure|
|---|---|---|---|
|Index|Yes|manifest parser inserts these|—|
|URLs|Yes|video must exist and be available (checked by fetching its info from YouTube, no download)|row error, skip row, report reason|
|Song title|No|—|row warning, included anyway|
|Artist|No|—|row warning, included anyway|
|Time range|Yes|`m:ss-m:ss` or `h:mm:ss-h:mm:ss`; `.` is accepted as the separator, since people type it; any dash type (`-`, `–`, `—`, as phones insert). Stray spaces inside numbers are ignored. Seconds must be two digits (`1.5` is ambiguous). start < end, and **end ≤ the video's length on YouTube**|row error, skip row, report reason|
|Mirrored แล้ว|No|empty or only spaces = not mirrored yet; anything else (any text or symbol) = already mirrored|— (used by the Mirror rule below)|

Note: because the URL and length checks ask YouTube, building the manifest needs internet. With `max_parallel_lookups` at once it averages about 0.6 s per row (2026-09: 12 rows in about 7 s), so a 300-row list takes a few minutes. It still happens before any download, so a bad row never costs a download.

**Row range:** a run can be limited to part of the sheet, e.g. rows `2-40` today and `41-80` tomorrow, so a long list can be done in sections. Rows are numbered exactly as Google Sheets shows them (the header is row 1, so the first song is row 2). A single number such as `5` means `5-5`. No range = all rows. A backwards range, or one outside the sheet, stops the run with a message naming the problem. Operators set it in the GUI with a "from" and a "to" field, where **an empty field is an open edge**: from 3 with an empty "to" means row 3 to the last row; an empty "from" with to 10 means the first song row to row 10; both empty means all rows. On the command line it's `--rows first-last`.

**Mirror rule** (`processing.mirror`):

1. `mirror = true` — **mirror everything:** every song ends up mirrored. Rows already marked in `Mirrored แล้ว` are left as they are (not flipped twice); all others get flipped.
2. `mirror = false` — **leave as is:** nothing is flipped, whatever the column says.

Countdowns are never mirrored.

Define the **error vs. warning taxonomy** once, explicitly:

- **Error** = data that would crash or corrupt the pipeline → row skipped, reported to GUI.
- **Warning** = data that's cosmetically incomplete but safe → row included, reported to GUI.

## 9. Pipeline Stages (detailed)

Turn your numbered usage scenario into a state machine / stage list with **inputs, outputs, and failure behavior** per stage. You already have the narrative — formalize it:

|Stage|Input|Output|Failure behavior|
|---|---|---|---|
|1. Lock settings|(run start signal?)|settings frozen for this run|—|
|2. Fetch sheet|Sheet URL (or a local CSV if the live fetch fails), row range (§8)|raw rows, limited to the row range|bad row range → abort with a message. Sheet unreachable/private (e.g. HTTP 401: asks whether it's shared as "Anyone with the link"), or a `[sheet.columns]` header not found (names the missing header and lists the ones found) → abort run before any download. Both verified against Google (TECH §4)|
|3. Prepare countdown|countdown choice (§7): URL or local file|cached countdown media|A URL is looked up and downloaded like a song (same retry policy, same cache key). Still failing after retries → **abort the run**: every song needs a countdown before it. Done *before* the manifest on purpose: one lookup up front means a bad countdown fails in seconds, not after minutes of row checks<br>**Planned (slice 6):** a cached countdown is not looked up on YouTube again (see stage 4). In **video** mode, a countdown with no picture (e.g. an `.mp3`) is shown as a **black screen** with its sound, plus one warning per run. Nothing else is drawn: on-screen text could never line up with the countdown's own ticks anyway. In audio mode, a video countdown simply gives its sound.|
|4. Build manifest|raw rows + video info from YouTube (no download)|validated manifest + per-row errors/warnings, plus a progress event per row|see §8. Look-ups run up to `max_parallel_lookups` at once and are retried up to `max_retries` times, but only when a retry could help (a network hiccup, not a removed video). Results, errors and warnings are always reported **in sheet order**, even though rows finish out of order. Each video is looked up once; the download reuses that information<br>**Planned (slice 6), cache-aware checking:** a row whose file for this run's mode is already cached skips the YouTube check; its length is measured from the file (exact), and the file being there proves it's available. Only new songs are looked up. A rerun of a fully cached list makes no YouTube requests.|
|5. Download songs|manifest URLs|cached song media|skip if already cached (resume-safe). Up to `max_parallel_downloads` at once; retry each up to `max_retries` times, then row error.<br>**Planned (slice 6), smarter retries:** two kinds of YouTube failure get two different responses. The occasional 403 is retried with uneven, slightly randomised waits that grow each time (exact values from a short measurement), so retries don't arrive in lockstep. "Sign in to confirm you're not a bot" / HTTP 429 means the connection is being limited, and retrying soon makes it worse: no new requests are started, work already finished is kept (cached songs stay cached), and the run stops with a clear message to wait and run again.|
|6. Check & measure|cached media, time ranges|real length + loudness peak of each clip|YouTube's length is rounded to whole seconds, so the real file is re-checked. End time past the real length by **about 1 s or less → trim to fit, row warning**. More than that → row error, skip. A (nearly) silent clip (peak ≤ −60 dB) gets no volume boost and a row warning.<br>**Crossfade per join:** each join gets the setting, or the most its two clips can hold without their fades overlapping, whichever is smaller (a clip with fades on both sides must keep at least one frame to itself; this also guarantees a clean cut point inside every countdown for chunking). The end fade-out follows the same rule. A shortened join gives a row warning for a song; a short countdown gives **one** warning per run, not one per join. A clip under 3 frames (0.1 s) aborts the run (countdown) or is a row error (song).<br>**Short streams:** if a clip's real audio or video is more than 0.5 s shorter than the planned clip (padding included), row warning (countdown: once per run). Smaller gaps, normal in real files, are padded silently|
|7. Render|countdown + songs in sequence, settings|final output file|Trim with padding, mirror (per §8 Mirror rule), peak normalization (always on), crossfades and countdowns. Every segment is forced to exactly its planned length (audio padded with silence or cut, video by repeating the last frame), so small gaps in real files never add up. Audio in one FFmpeg run; video in chunks of 6 songs (§6).<br>**Only a checked output gets its final name:** the render writes `<name>.rendering.<ext>`; after the output length matches the plan it's renamed to the final name, otherwise to `<name>_FAILED.<ext>`, including when FFmpeg fails after writing something. Leftover `*.rendering.mp3` / `*.rendering.mp4` files from a crash are deleted at the start of the next run (only that exact pattern; a locked one is skipped with a warning). Protocol: if a specific song is known bad, warn and skip it; don't kill the whole compilation. **End fade-out:** the last song fades to silence and to black over the crossfade duration, ending exactly at the end of the output, which keeps its planned length. Hard-coded, no setting. The core decides the fade (it's part of the render plan); the renderer applies it, with a curved audio fade so the very end is fully silent<br>**Planned (slice 6), render progress:** rendering is never a silent, still bar. The FFmpeg adapter reports how much of the planned output has been written, as plain done/total numbers, so the GUI shows a filling bar with a percentage (e.g. "Rendering 63%"). Any step that can't report a percentage still shows moving feedback (see GUI.md 2.3).|
|8. Unlock GUI|run end|settings in the GUI editable again|—|

**Stopped by the operator:** in the GUI, the Run button becomes Stop during a run, and stopping asks for confirmation first. A stopped run ends like any failed one: nothing unverified gets the final output name (anything already rendered becomes `_FAILED`; a stopped *video* render usually leaves nothing, since its output file only exists after the final join), songs already downloaded stay cached (a download that's already merging is allowed to finish), and interrupted downloads are cleaned up. A YouTube look-up already in progress finishes first, so a stop can take a couple of seconds: a clean result matters more than a fast stop. Then the GUI unlocks. Measured 2026-09: a live run ends within about 2–4 s of Stop.

## 10. Caching Strategy

- Cache key: `{videoID}_{audio|v<max_height>}`, e.g. `abc123_audio`, `abc123_v720`. The ID alone identifies the video; the suffix separates audio-only from video downloads, so each mode downloads its own file once. The `v` number is the `max_height` setting, not the file's real height, so changing that setting never reuses a lower-quality file.
  - No title or artist in the key: titles can contain characters Windows forbids in filenames, and fixing a typo on the sheet would otherwise cause a re-download. Titles appear in the logs instead.
  - The manual-download naming rule (for dropping a file into the cache by hand) is in HANDOFF.md.
- Cache location: from `[download]`. Default under `workspace/cache/` (gitignored, §15).
- Invalidation: cache never expires on its own; clearing it depends on the operator's machine (plenty of disk and quick iteration, or very limited space).
  - **GUI:** no question after a run. A warning line at the end of the log reminds the operator how much the cache holds, and the Clear cache button (with a confirmation) is always there.
  - **Terminal (`run.bat` / `run.sh`):** asks after each successful run (default: No), since there's no button there.
- Clearing deletes **only** files named by the cache key rule above, plus leftovers of interrupted downloads, never anything else in the folder. Because it matches by name pattern, the cache must live in a folder of its own (§7): an operator file that happens to fit the pattern would be deleted.

## 11. Logging & Observability

- Core streams structured log events to GUI in real time (already decided).
- Define **log levels** and what triggers each (INFO for stage transitions, WARNING for row warnings, ERROR for row errors/aborts).
- Every run writes a log file, `workspace/logs/<date>_<time>.log`, named by when the run **started** (not every run produces an output to name it after).
- The log file always includes debug detail the console hides, above all the exact FFmpeg commands. The console is for the operator watching the run; the file is for whoever investigates afterwards.
- Only the 5 newest log files are kept, counting the current run's (sweet spot between "collect everything" and "collect nothing"). Older ones are deleted at the start of a run.

## 12. Output Layout

Where files land, naming convention, and whether intermediate files (per-song trims, mirrored clips) are kept or cleaned up after the final concat. Cleanup policy matters for disk space on whatever machine this runs on year over year.

- Git management: all generated data (downloads, cache, intermediates, outputs, logs) lives under `workspace/`, which is gitignored. Nothing generated ever goes into git (§15).
- Output formats: video `.mp4` (format fixed in §7), audio-only `.mp3`.
- Default folders are inside `workspace/` (`output/`, `cache/`, plus a temporary work folder); they're recreated if missing. The operator may point output and cache anywhere (§7).

## 13. Coding Standards

Write these down explicitly — this is the section that actually protects "passed within generations":

- Style: PEP 8 + type hints on all public functions.
- Docstrings: Google-style convention, stick to it.
- No GUI imports in core modules (§5).
- Config is read once per run, not polled, and written once at run start (§7) — comment this in code, not just here.
- Testing (minimum, decided): smoke tests using the tiny clips in `tests/fixtures/`, with fake song-list and media sources and the real FFmpeg processor. Fully offline: no downloading, no YouTube, no sheet. They check the output **length** against the plan, not just that a file exists, since FFmpeg can succeed while producing a broken file. Standard-library `unittest`, so nothing extra to pin. Must pass before any merge to `main`.
- TODO: testing beyond the smoke test — maybe unit test per module? (each module eats input and vomits the expected outcome)

**Development lifecycle: spec-driven, iterative, in thin vertical slices.**

- Start with a walking skeleton — the thinnest version of the _whole_ pipeline (e.g. two hardcoded songs, no GUI, one output file) — then thicken one capability at a time. Never build stage-by-stage; every slice must end in something that runs.
- **Seeing each slice actually run is the self-validation.** A slice that produces real output is judged against reality, not against a plausible-looking diff. Acceptance condition is written _before_ the slice starts, so "Claude produced something plausible" can't pass as "it works."
- **Revisit this spec every time a slice settles**, before merging. The maintainer decides which side moves: change the spec to match reality, or change the code to match the spec. Spec and code move in the same commit, or the spec quietly becomes fiction for the next generation.
- Definition of done for a slice: acceptance condition met + smoke test passes + spec revisited + merged to `main` (§15). Tag CalVer when a slice is genuinely usable, not every merge.
- Claude Code works on branches, behind ports, and may draft ports — but a port is _approved_ by the maintainer before implementation follows (two-step slice). See `CLAUDE.md`.

## 14. Known Limitations / Open Questions

Running list — append here instead of losing the thought between sessions.

- Google Sheet cloned from private Gmail instead of group Gmail — operator error, not enforced in code. Revisit if it becomes a recurring problem.
- YouTube reports song length rounded to whole seconds, so the early check (§8) can't catch every overrun; the after-download check (§9 stage 6) stays as the second guard.
- Sheet column mapping is file-only for now (§7). A future generation can expose it in the GUI if the sheet layout changes often.
- YouTube may rate-limit a connection after heavy use ("Sign in to confirm you're not a bot", then HTTP 429). It clears on its own after an hour or more; HANDOFF tells the operator to wait and retry. Using browser cookies would avoid it, but borrows a logged-in account's session, so it's deliberately not supported for now (maintainer decision 2026-09-28; see HANDOFF upgrades).
- When Open file / Open folder can't open something (e.g. no media player installed), the reason only appears in the background console, not in the window's log. Small fix for a future slice: show it in the log as a warning.
- Every run re-checks every row on YouTube, even when all songs are cached, which makes the rate limit above more likely, especially on a fast connection (tested 2026-09 on Ubuntu: a cached countdown still triggered the bot check). Fix planned in slice 6 (cache-aware checking, §9 stage 4; smarter retries, §9 stage 5).

## 15. Repository & Version Control

**Guiding principle: the repo holds the recipe, never the ingredients or the cooking.**

- Code → in git.
- Data (videos, cache, outputs, logs) → never in git; lives in `workspace/` (gitignored).
- Config → committed template `config/example.toml`; the live `config/config.toml` is gitignored because each generation fills in its own, and it's generated from the template on first run (§7).
- Credentials (e.g. Google service account JSON) → never committed, not even once. Explain in README where to get one.

Layout:

```
larb-spicy/
├── README.md             # for humans: what it is, how to run in 3 steps
├── CLAUDE.md             # house rules for Claude Code (committed)
├── docs/SPEC.md          # this document
├── docs/HANDOFF.md       # decisions + gotchas for next generation
├── docs/TECH.md          # implementation notes: the how (SPEC wins on conflict)
├── requirements.txt      # exact == pins, everything except yt-dlp (platform markers for Linux-only / 3.11-only packages)
├── python-range.txt      # supported Python range, e.g. 3.11-3.13; the only place it's written
├── .gitattributes        # keeps .sh files in LF and .bat files in CRLF line endings
├── setup_once.bat / .sh  # thin: find or install a Python, then hand over
├── run.bat / .sh         # thin: same, then start the program
├── tools/find_python.*   # the "get a suitable Python" step, per OS
├── tools/env_setup.py    # everything after that, shared by all OSes
├── config/example.toml   # committed template
├── config/config.toml    # live settings, gitignored
├── src/larb/core/        # rules + orchestration, ports, models, errors (stdlib only)
├── src/larb/adapters/    # TOML, sheet, yt-dlp, FFmpeg, console
├── src/larb/app.py       # the one place adapters are connected to ports
├── src/larb/cli.py       # terminal front end: python -m larb <sheet> [--countdown <file or URL>] [--rows first-last];
│                         #   with no arguments, python -m larb opens the window
├── src/larb/gui/         # the window (docs/GUI.md); its decisions live in gui/state.py, testable without Tkinter
├── tests/                # offline tests
├── tests/fixtures/       # tiny clips for the tests
└── workspace/            # gitignored
```

Git workflow:

- `main` = known-good, always runs. Nothing lands on `main` without the smoke test passing.
- **One branch per slice**, named after what it does (e.g. `skeleton`, `fade-out`, `gui`), created from an up-to-date `main`. Claude Code works only on that branch. Merging is a deliberate human act; the branch is deleted after merging.
- Known-good releases are tagged with CalVer (`<year>.<index>`), so successors can always fall back to one.
- `.gitignore` is written before the first commit (`workspace/`, `config.toml`, credentials, `.venv/`, `CLAUDE.local.md`).

Claude Code:

- `CLAUDE.md` is committed — it's project rules, true for anyone (including successors using Claude)
- `CLAUDE.local.md` holds personal notes/paths and is gitignored.

## 16. Environment & Setup Scripts

Dependency strategy: **stable where possible, fresh where necessary.**

- Everything is pinned to known-good versions (`requirements.txt`, exact `==`), except yt-dlp.
- yt-dlp is always latest, because an outdated yt-dlp is what breaks. Installed on its own line in the scripts, so nobody pins it (or unpins everything else) by accident.
- Python is pinned to a tested range (§6). Pinned Python + pinned libraries age together consistently.
- FFmpeg comes from `static-ffmpeg` inside the venv (pinned). The fallback system FFmpeg is outside Python: checked, not managed by the venv. No JS runtime is required (§6).

Key fact: a venv is a folder of libraries pointing to one specific installed Python. It isolates libraries and pins their versions, while the **scripts** guarantee the Python version. The venv is disposable: rebuilding it is always safe.

**How the work is split:** the shell scripts (`.bat` for Windows, `.sh` for Linux/Mac) have one job: get a suitable Python. Everything after that lives in one shared Python script (`tools/env_setup.py`), so each rule is written once, not once per shell language.

Supported range: `python-range.txt`. Every version in it has passed the full test suite (2026-09: 3.11, 3.12, 3.13 on Windows; 3.13 on Linux). The version **offered for install** is the newest in the range.

`setup_once`:

1. **Get a suitable Python** (shell scripts). Use one in the range if installed. If there's none (no Python at all, or only versions outside the range, like a too-new one), say which version to get and that it installs **alongside** the existing Python, with nothing to uninstall. Then ask before installing: `winget` on Windows, `brew` on Mac, and install after a yes. On Linux, print the exact command instead (no `sudo` from scripts); on some distros that includes adding the deadsnakes package archive, since they ship only a newer Python. If winget is missing or the user declines, point to python.org. After an install, tell the user to open a new terminal and run setup again.
2. Build the venv with that Python.
3. Install pinned libraries + latest yt-dlp.
4. Get FFmpeg: trigger the `static-ffmpeg` download now (about 45 s and 200 MB the first time), so the first real run doesn't stall. If that fails → use system FFmpeg if it's 7.1 or newer → else ask whether to install it (`winget` on Windows, `brew` on Mac; on Linux, print the command, with a warning that the distro's FFmpeg may be older than 7.1). After installing, tell the user to reopen the terminal and run setup again.
5. On Linux, check that tkinter is available (the GUI needs it), and that fonts for Thai, Korean and Japanese are installed (song titles use them); print the install command for anything missing. Windows ships all of these.
6. Always pause at the end, so a double-clicked window stays readable.

Running `setup_once` again is safe and fast (seconds): nothing is rebuilt unless something is missing or out of range. Measured 2026-09: first setup about 3 minutes on Windows and on Linux.

Tested 2026-09 on Windows 11, WSL Ubuntu 26.04, and a real Ubuntu 24.04 PC (which ships Python 3.12, in range; there, setup's tkinter hint was the only step needed).

`run`:

1. Venv missing, or its Python outside the range → rebuild it automatically, **announcing it first** (it includes the one-time FFmpeg download, so it can take minutes). If `requirements.txt` changed since the last install (e.g. after a `git pull`), reinstall the libraries.
2. `pip install -U yt-dlp` (not `yt-dlp -U`, which is for the standalone binary). No internet → warn and continue with the installed version.
3. Log the yt-dlp version (first suspect when downloads break), then start the program with UTF-8 output, so Thai titles print correctly.
4. Started with no arguments (e.g. double-clicked) → **open the window**. On Windows the console restarts minimized, titled "LARB - Spicy (console)": out of sight, but still in the taskbar if something fails before the window opens. It closes after a normal exit and stays open after a failure, so the error can be read. With arguments → the terminal version, as before.

The program itself never downloads FFmpeg: a run uses static-ffmpeg only if it's already downloaded, otherwise the system FFmpeg.

## 17. Maintenance & Hand-off

`docs/HANDOFF.md` must include at least:

- "Downloads failing? Update yt-dlp first. If still failing, it may need a JS runtime (Deno is yt-dlp's default; Node works if passed explicitly)."
- Python update recipe (expect every few years, when yt-dlp drops an end-of-life Python):
    1. Install the new Python _alongside_ the old one (`setup_once` can offer it, or use python.org); don't uninstall yet.
    2. Change the range in `python-range.txt`.
    3. Delete the `.venv` folder, then run `setup_once`. (It only rebuilds by itself if the old Python fell outside the range.)
    4. Run the smoke test. Pass → commit and tag a new CalVer release; only then uninstall the old Python. Fail → usually a pinned library needs bumping; hand the error to an AI.
- When to consider updating ports? : idk yet, When it traced the error to this port and the library is old as heck, or maybe just adjust dependency version, then check compatibility? lightwork.