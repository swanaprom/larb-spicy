**Version:** 2026.1 (CalVer: `<year>.<index_of_versions_in_same_year>`)

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
|Padding|Each song is taken 1 s earlier and 1 s later than its sheet time range (clamped to the song's real start/end), so the crossfade doesn't eat into the part the dancers need|
|File-only setting|A config key that exists only in `config.toml` and is never shown in the GUI. For maintainers who have re-tested a change, not for operators (§7)|
|Peak normalization|Each clip's loudest point is raised or lowered to the same level (−1 dBFS), so quiet countdowns and loud songs sit together without flattening the music|

## 5. Architecture Overview

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
  EventSink         report progress, warnings, errors         console now, GUI later
```

Adapters can be replaced without touching the core, as long as the port stays the same. Port signatures change only with the maintainer's approval (CLAUDE.md).

**Module boundary rule (maintainability keystone):** the GUI never touches yt-dlp/FFmpeg directly, and the core never imports GUI code. If you can't unit-test a core module without spinning up the GUI, the boundary has leaked.

**Concurrency model:** settings loaded once at pipeline start (you already decided this — restate it here so it doesn't get "fixed" by someone who reads only the GUI code and assumes live reloading is a bug).

## 6. Tech Stack

|Concern|Choice|Notes / alternatives considered|
|---|---|---|
|Language|Python 3.11–3.13 (tested range)|Pinned as a range, not loose: the venv can't upgrade its own Python, and a new Python can break pinned libraries. 3.11 is also the floor for `tomllib`. Range lives in one file read by both scripts (§16)|
|Video/audio download|`yt-dlp` (always latest, not pinned)|replaces `moviepy` download path from prototype. The only unpinned dependency — see §16|
|FFmpeg binary|pip-bundled binary (`static-ffmpeg`), **FFmpeg 7.1 or newer**|Lives in the venv, pinned with it, no admin rights needed. Fallback: a system FFmpeg, if it's 7.1 or newer; else prompt the operator to install one. Why 7.1: long song lists need an option only 7.1+ has, and one version rule means one tested code path. An older FFmpeg stops the run with a clear "too old" message|
|JS runtime (Deno / Node)|**Not required** — add only if yt-dlp actually breaks without one|2026-09 spike: downloads work without one (yt-dlp prints a deprecation warning). Node also works if passed explicitly. If it ever becomes necessary, same handling as system-bound FFmpeg (check + ask). Note kept in HANDOFF.md|
|Trim / mirror / crossfade|FFmpeg via `subprocess`, through one internal helper module; **whole compilation rendered in one pass**|Helper owns every FFmpeg call, keeps binary path separate from the argument list. One pass confirmed in the spike (exact lengths, A/V in sync). Very long video lists are rendered in chunks and joined without re-encoding (TECH §10)|
|GUI framework|Tkinter (`ttk`)|Zero dependencies (nothing to pin, nothing that can vanish from PyPI), most examples for AI-assisted successors, and enough styling (colors, fonts, log tags) for the actual UI. Rejected: Qt/PySide6 (heavy + licensing questions), CustomTkinter (third-party, risks lagging a Python bump), PySimpleGUI (now needs a license key).|
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
default_urls = []
default_files = []

[download]
cache_directory = ""     # empty = workspace/cache/. The operator may choose any folder.
max_parallel_downloads = 3   # file-only. Tested best for video; more is slower on a full connection (TECH §9)
max_retries = 2              # file-only. Retries per song before it becomes a row error (TECH §9)
max_height = 720             # file-only. Largest video height to download, in pixels (720 = "720p").
                             # Also the output height: output is never taller than this. Even number, 144–4320.
# Codec preference when downloading (prefer H.264) is hard-coded in the downloader adapter:
# it depends on what each download tool can do, and H.264 is also much faster to render (TECH §9).
# TODO: timeout — yt-dlp has its own network timeout/retry options; decide in the downloader slice whether they're enough.

[processing]
audio_only = true
mirror = false                   # two modes, see §8 "Mirror rule"
crossfade_duration_seconds = 1.0 # above 0, at most 10. There is no "no crossfade" option by design.
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

Note: because the URL and length checks ask YouTube, building the manifest needs internet and takes roughly 0.5–3 s per row. It still happens before any download, so a bad row never costs a download.

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
|2. Fetch sheet|Sheet URL, row range (or just plain CSV if it fails to use the live fetch)|raw rows|sheet unreachable/private (e.g. HTTP 401: asks whether it's shared as "Anyone with the link"), or a `[sheet.columns]` header not found (names the missing header and lists the ones found) → abort run before any download. Both verified against Google (TECH §4)|
|3. Build manifest|raw rows + video info from YouTube (no download)|validated manifest + per-row errors/warnings|see §8|
|4. Download countdown|countdown URL/file or default|cached countdown media|Use same retry policy as the row below.|
|5. Download songs|manifest URLs|cached song media|skip if already cached (resume-safe). Up to `max_parallel_downloads` at once; retry each up to `max_retries` times, then row error.|
|6. Check & measure|cached media, time ranges|real length + loudness peak of each clip|YouTube's length is rounded to whole seconds, so the real file is re-checked. End time past the real length by **about 1 s or less → trim to fit, row warning**. More than that → row error, skip. A (nearly) silent clip (peak ≤ −60 dB) gets no volume boost and a row warning|
|7. Render (one pass)|countdown + songs in sequence, settings|final output file|Trim with padding, mirror (per §8 Mirror rule), peak normalization (always on), crossfades and countdowns all in one FFmpeg run. Protocol: if a specific song is known bad, warn and skip it; don't kill the whole compilation. **Planned (slice 1):** the last song fades out at the end, audio and video, over the crossfade duration (hard-coded, no setting)|
|8. Unlock GUI|(run end signal?)|settings GUI and TOML editable again|—|

## 10. Caching Strategy

- Cache key: `{videoID}_{audio|v<max_height>}`, e.g. `abc123_audio`, `abc123_v720`. The ID alone identifies the video; the suffix separates audio-only from video downloads, so each mode downloads its own file once. The `v` number is the `max_height` setting, not the file's real height, so changing that setting never reuses a lower-quality file.
    - No title or artist in the key: titles can contain characters Windows forbids in filenames, and fixing a typo on the sheet would otherwise cause a re-download. Titles appear in the logs instead.
    - The manual-download naming rule (for dropping a file into the cache by hand) is in HANDOFF.md.
- Cache location: from `[download]`. Default under `workspace/cache/` (gitignored, §15).
- Invalidation: cache never expires on its own. After each run the operator is asked whether to clear it, since that depends on their machine (plenty of disk and quick iteration, or very limited space). A clear-cache button is also always available in the GUI.

## 11. Logging & Observability

- Core streams structured log events to GUI in real time (already decided).
- Define **log levels** and what triggers each (INFO for stage transitions, WARNING for row warnings, ERROR for row errors/aborts).
- Log file from GUI stream persists to disk per run, always keep 5 latest log (sweet spot between 'collect everything' and 'collect nothing').

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
- TODO: name of the Python version-range file read by both scripts.

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
├── requirements.txt      # exact == pins, everything except yt-dlp
├── <python range file>   # single source of truth for supported Python
├── setup_once.bat / .sh
├── run.bat / .sh
├── config/example.toml   # committed template
├── config/config.toml    # live settings, gitignored
├── src/larb/core/        # rules + orchestration, ports, models, errors (stdlib only)
├── src/larb/adapters/    # TOML, sheet, yt-dlp, FFmpeg, console
├── src/larb/cli.py       # entry point: python -m larb <sheet> --countdown <file>
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

Key fact: a venv is a folder of libraries pointing to one specific installed Python. It isolates libraries and specify their versions, while the **scripts** guarantee the Python version.

`setup_once`:

1. Find a Python in the supported range (Windows: `py -0` lists installed, `py -3.12` picks one; Linux/Mac: try `python3.12`, `python3.13`, ...). None found → Offer `winget` (or some package manager method for linux) or point to python.org (Windows: tick "Add to PATH") and stop.
2. Build the venv with that Python.
3. Install pinned libraries + latest yt-dlp.
4. Get FFmpeg: trigger the `static-ffmpeg` download now (about 45 s and 200 MB the first time), so the first real run doesn't stall. If that fails → use system FFmpeg if it's 7.1 or newer → else ask whether to install it (`winget` on Windows, `brew` on Mac; on Linux, print the command). After installing, tell the user to reopen the terminal and run setup again.

`run`:

1. Venv missing, or its Python outside the range → rebuild it automatically.
2. `pip install -U yt-dlp` (not `yt-dlp -U`, which is for the standalone binary). No internet → warn and continue with the installed version.
3. Log the yt-dlp version (first suspect when downloads break), then start the program.

## 17. Maintenance & Hand-off

`docs/HANDOFF.md` must include at least:

- "Downloads failing? Update yt-dlp first. If still failing, it may need a JS runtime (Deno is yt-dlp's default; Node works if passed explicitly)."
- Python update recipe (expect every few years, when yt-dlp drops an end-of-life Python):
    1. Install the new Python from python.org _alongside_ the old one; don't uninstall yet.
    2. Change the range in the Python range file.
    3. Run `setup_once` (rebuilds the venv).
    4. Run the smoke test. Pass → commit and tag a new CalVer release; only then uninstall the old Python. Fail → usually a pinned library needs bumping; hand the error to an AI.
- When to consider updating ports? : idk yet, When it traced the error to this port and the library is old as heck, or maybe just adjust dependency version, then check compatibility? lightwork.