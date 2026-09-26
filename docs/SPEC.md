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
3. **Efficiency** — faster than the `moviepy` prototype (target: TODO — put a number here once you have a baseline, e.g. "under N minutes for M songs on reference hardware"). Which currently aimed to use FFmpeg.

## 3. Non-Goals

Explicit "we are not doing this, and here's why" — this is what stops scope creep from a future maintainer who tries to be helpful.

- Not enforcing Google Sheet sharing/visibility settings (operator's job — document the checklist in the README, don't code around human error).
- Not guaranteeing millisecond-accurate trims at download time (full-song download + trim is the deliberate tradeoff for maintainability, per your prototype-carried-forward decision).
- Not doing the OS-specific releases. Learning curve is flat, Maintainers can rely on AI reading README and follow straight forward instruction. Distribution is clone + setup scripts instead (§16). A frozen executable (e.g. PyInstaller) would also freeze yt-dlp inside it, and an outdated yt-dlp is exactly what breaks when YouTube changes. It would also need per-OS builds and trigger antivirus / "unidentified developer" warnings.
- Not using `make`. Windows doesn't ship it, and the most likely successor is on Windows.

## 4. Glossary

Keep this current — a future non-technical maintainer will live here.

|Term|Meaning|
|---|---|
|Manifest|The parsed, validated table derived from the Google Sheet, used to drive the pipeline|
|Countdown|Intro video/audio clip inserted before each song|
|Cache|Previously-downloaded media kept on disk keyed by `videoID_songtitle_artist` to survive interrupted runs|
|Row error|A manifest row that fails validation and is skipped, with a reported reason (missing "URL" or "start_time" or "end_time")|
|Row warning|A manifest row with a non-critical issue (e.g. missing "Song Name") that still runs|

## 5. Architecture Overview

A short narrative + a diagram (even ASCII) beats prose alone here, since this is the thing that decays fastest in your memory between sessions.

```
[setup_once] --> [run] --> [GUI]

[GUI] --(config edits)--> [TOML settings file] <--(load once per run)-- [Core Orchestrator]

[GUI] --(sheet URL, countdown URL/file, row range)--> [Core Orchestrator]

Core Orchestrator
  ├─ Config Manager      -> call config reader/writer port (TOML) 
  ├─ Sheet Fetcher       -> call raw rows fetcher port
  ├─ Manifest Builder    -> validated manifest (+ row errors/warnings)
  ├─ Downloader          -> call downloader port (yt-dlp) + cached media files
  ├─ Media Processor     -> call helper to trim / mirror / crossfade (FFmpeg)
  └─ Logger              -> signal observer to stream to GUI
```

**Module boundary rule (write this down, it's the maintainability keystone):** the GUI never touches yt-dlp/FFmpeg directly, and the core never imports GUI code. If you can't unit-test a core module without spinning up the GUI, the boundary has leaked.

**Concurrency model:** settings loaded once at pipeline start (you already decided this — restate it here so it doesn't get "fixed" by someone who reads only the GUI code and assumes live reloading is a bug).

## 6. Tech Stack

| Concern                   | Choice                                                                              | Notes / alternatives considered                                                                                                                                                                                                                                                                                                                                                          |
| ------------------------- | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Language                  | Python 3.11–3.13 (tested range)                                                     | Pinned as a range, not loose: the venv can't upgrade its own Python, and a new Python can break pinned libraries. 3.11 is also the floor for `tomllib`. Range lives in one file read by both scripts (§16)                                                                                                                                                                               |
| Video/audio download      | `yt-dlp` (always latest, not pinned)                                                | replaces `moviepy` download path from prototype. The only unpinned dependency — see §16                                                                                                                                                                                                                                                                                                  |
| FFmpeg binary             | pip-bundled binary (`static-ffmpeg`)                                                | Make it env-bounded, can pin working version, just have system-bound existence and version check (4.3 and newer), in case the library's repo failed to fetch, and prompt operator to download FFmpeg if it's needed. (Reduced friction)                                                                                                                                                  |
| JS runtime (Deno)         | Only if testing proves yt-dlp needs it for YouTube                                  | Same handling as system-bound FFmpeg (check + ask). If not needed, leave a note in HANDOFF.md instead                                                                                                                                                                                                                                                                                    |
| Trim / mirror / crossfade | FFmpeg (`xfade`) via `subprocess`, through one internal helper module               | Helper owns every FFmpeg call, keeps binary path separate from the argument list.                                                                                                                                                                                                                                                                                                        |
| GUI framework             | Tkinter (`ttk`)                                                                     | Zero dependencies (nothing to pin, nothing that can vanish from PyPI), most examples for AI-assisted successors, and enough styling (colors, fonts, log tags) for the actual UI. Rejected: Qt/PySide6 (heavy + licensing questions), CustomTkinter (third-party, risks lagging a Python bump), PySimpleGUI (now needs a license key).                                                    |
| Config format             | TOML — `tomllib` (read, 3.11+) + `tomli-w` (write, pinned)                          | Python has no built-in TOML writer. But align best among the goals.                                                                                                                                                                                                                                                                                                                      |
| Sheet access              | Public CSV export URL + standard library (`csv`)                                    | No credentials to inherit or expire, no Google Cloud console for a successor, already tested including the special-character/encoding fix. Matches the §3 non-goal on sharing settings. Local CSV file stays as fallback (§9 stage 2). Rejected API + service account: only buys private-sheet reads and write-back, neither needed. Revisit if writing back to the sheet is ever wanted |
| Packaging                 | Clone repo + `setup_once` / `run` scripts (`.bat` for Windows, `.sh` for Linux/Mac) | Plain `python -m venv` + `requirements.txt` with exact `==` pins. No extra tools needed beyond Python itself. Rejected: PyInstaller releases, `make` (see §3)                                                                                                                                                                                                                            |

## 7. Configuration Schema (TOML)

Write the actual schema, not just "it's configurable." This is the contract between GUI and core.

```toml
[output]
directory = ""
filename_template = ""   # {date}_{time}.mp4 — date + time only, no event name (ordering by time is sufficient; keeps the GUI uncramped)

[countdown]
default_urls = []
default_files = []

[download]
cache_directory = ""
# TODO: retry count, timeout, format/quality selection for yt-dlp

[processing]
audio_only = true
mirror = false
crossfade_duration_seconds = 1.0
# TODO: resolution/codec targets (only apply for videos)

[sheet]
# TODO: expected column headers, in order, e.g.
# columns = ["Member Name", "Song URL", "Song Name", "Start Time", "End Time"]
```

**Read rule:** GUI requests settings detail from core program ONLY on open to resume the change.

**Write rule (revised):** GUI edits live in memory. On blur/enter the core validates the field and pings the corrected value back to the GUI (e.g. clipping an out-of-bound value), but does **not** write to disk. The whole config is validated and written **once, when Run is hit** — which doubles as a whole-settings consistency check before every run. Write is atomic (temp file + rename).

- Consequence: edits are lost if the GUI is closed without running → also save (or prompt) on close.
- TODO: still document per-field validation behavior — non-existent directory: clamp, reject, or warn?

## 8. Manifest Schema & Validation Rules

This is the section most likely to save you future debugging time — write the rule table now while it's fresh.

|Column|Required?|Validation|On failure|
|---|---|---|---|
|Index|Yes|manifest parser insert these|—|
|Song URL|Yes|must be a resolvable URL/valid yt-dlp source|row error, skip row, report reason|
|Song Title|No|—|row warning, included anyway|
|Artist Name|No|—|row warning, included anyway|
|Start/End Time|Yes|format check (mm:ss? plain seconds?)|row error, skip row, report reason|
|...||||

Define the **error vs. warning taxonomy** once, explicitly:

- **Error** = data that would crash or corrupt the pipeline → row skipped, reported to GUI.
- **Warning** = data that's cosmetically incomplete but safe → row included, reported to GUI.

## 9. Pipeline Stages (detailed)

Turn your numbered usage scenario into a state machine / stage list with **inputs, outputs, and failure behavior** per stage. You already have the narrative — formalize it:

|Stage|Input|Output|Failure behavior|
|---|---|---|---|
|1. Lock settings|(run start signal?)|settings frozen for this run|—|
|2. Fetch sheet|Sheet URL, row range (or just plain CSV if it fails to use the live fetch)|raw rows|sheet unreachable/private → abort run with clear message (ties to Non-Goal in §3)|
|3. Build manifest|raw rows|validated manifest + per-row errors/warnings|see §8|
|4. Download countdown|countdown URL/file or default|cached countdown media|retry policy? TODO|
|5. Download songs|manifest URLs|cached song media|skip if already cached (resume-safe)|
|6. Trim|cached full songs, start/end times|trimmed clips|— (It would be a bug, since manifest will check the format right away before parsed)|
|7. Mirror (optional)|trimmed clip, settings flag|mirrored clip|—|
|8. Crossfade/concat|countdown + trimmed clips in sequence|final output file|TODO: partial-failure behavior — one bad song shouldn't necessarily kill the whole compilation? decide and record (if it's know which song is bad, just warn the error and skip, this is the protocol)|
|9. Unlock GUI|(run end signal?)|settings GUI and TOML is able to be edit again|—|

## 10. Caching Strategy

- Cache key: TODO (videoID_songtitle_artistname) — Not including index in case the order change but the song is cached, videoID is a unique key already, the last two are for human.
- Cache location: from `[download]`. Default under `workspace/cache/` (gitignored, §15).
- Invalidation: cache never expires, It's prompt after a run to be clear or not, leave the room for operator decision (they can have big disk space and need quick iteration, or is very limited space). But still exist clear cache button on GUI anyway.

## 11. Logging & Observability

- Core streams structured log events to GUI in real time (already decided).
- Define **log levels** and what triggers each (INFO for stage transitions, WARNING for row warnings, ERROR for row errors/aborts).
- Log file from GUI stream persists to disk per run, always keep 5 latest log (sweet spot between 'collect everything' and 'collect nothing').

## 12. Output Layout

Where files land, naming convention, and whether intermediate files (per-song trims, mirrored clips) are kept or cleaned up after the final concat. Cleanup policy matters for disk space on whatever machine this runs on year over year.

- Git management: all generated data (downloads, cache, intermediates, outputs, logs) lives under `workspace/`, which is gitignored. Nothing generated ever goes into git (§15).

## 13. Coding Standards

Write these down explicitly — this is the section that actually protects "passed within generations":

- Style: PEP 8 + type hints on all public functions.
- Docstrings: Google-style convention, stick to it.
- No GUI imports in core modules (§5).
- Config is read once per run, not polled, and written once at run start (§7) — comment this in code, not just here.
- Testing (minimum, decided): one smoke test using 2–3 tiny fixture clips in `tests/fixtures/` — trim/crossfade them offline, check the output exists. No downloading. This is the baseline guard: must pass before any merge to `main`.
- TODO: testing beyond the smoke test — maybe unit test per module? (each module eats input and vomits the expected outcome)

**Development lifecycle: spec-driven, iterative, in thin vertical slices.**

- Start with a walking skeleton — the thinnest version of the _whole_ pipeline (e.g. two hardcoded songs, no GUI, one output file) — then thicken one capability at a time. Never build stage-by-stage; every slice must end in something that runs.
- **Seeing each slice actually run is the self-validation.** A slice that produces real output is judged against reality, not against a plausible-looking diff. Acceptance condition is written _before_ the slice starts, so "Claude produced something plausible" can't pass as "it works."
- **Revisit this spec every time a slice settles**, before merging. The maintainer decides which side moves: change the spec to match reality, or change the code to match the spec. Spec and code move in the same commit, or the spec quietly becomes fiction for the next generation.
- Definition of done for a slice: acceptance condition met + smoke test passes + spec revisited + merged to `main` (§15). Tag CalVer when a slice is genuinely usable, not every merge.
- Claude Code works on branches, behind ports, and may draft ports — but a port is _approved_ by the maintainer before implementation follows (two-step slice). See `CLAUDE.md`.

## 14. Known Limitations / Open Questions

Running list — append here instead of losing the thought between sessions.

- Millisecond-accurate segment download not solved (full download + trim tradeoff, §3).
- Google Sheet cloned from private Gmail instead of group Gmail — operator error, not enforced in code. Revisit if it becomes a recurring problem.
- TODO: name of the Python version-range file read by both scripts.

## 15. Repository & Version Control

**Guiding principle: the repo holds the recipe, never the ingredients or the cooking.**

- Code → in git.
- Data (videos, cache, outputs, logs) → never in git; lives in `workspace/` (gitignored).
- Config → committed template `config/example.toml` (Used as reference of how it should be generated); the real `config.toml` is gitignored because each generation fills in its own. So it needs to generate default value in first run.
- Credentials (e.g. Google service account JSON) → never committed, not even once. Explain in README where to get one.

Layout:

```
larb-spicy/
├── README.md             # for humans: what it is, how to run in 3 steps
├── CLAUDE.md             # house rules for Claude Code (committed)
├── docs/SPEC.md          # this document
├── docs/HANDOFF.md       # decisions + gotchas for next generation
├── docs/TECH.md          # this document
├── requirements.txt      # exact == pins, everything except yt-dlp
├── <python range file>   # single source of truth for supported Python
├── setup_once.bat / .sh
├── run.bat / .sh
├── config/example.toml
├── src/                  # manifest, download, render, cli ...
├── tests/fixtures/       # tiny clips for the smoke test
└── workspace/            # gitignored
```

Git workflow:

- `main` = known-good, always runs. Nothing lands on `main` without the smoke test passing.
- Claude Code works only on branches (`git switch -c <feature>` at the start of every session). Merging is a deliberate human act.
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
- Fallback system-bound FFmpeg (and Deno, if needed) are outside Python: checked, not managed by the venv.

Key fact: a venv is a folder of libraries pointing to one specific installed Python. It isolates libraries and specify their versions, while the **scripts** guarantee the Python version.

## 17. Maintenance & Hand-off

`docs/HANDOFF.md` must include at least:

- "Downloads failing? Update yt-dlp first. If still failing, it may need Deno (JS runtime)."
- Python update recipe (expect every few years, when yt-dlp drops an end-of-life Python):
    1. Install the new Python from python.org _alongside_ the old one; don't uninstall yet.
    2. Change the range in the Python range file.
    3. Run `setup_once` (rebuilds the venv).
    4. Run the smoke test. Pass → commit and tag a new CalVer release; only then uninstall the old Python. Fail → usually a pinned library needs bumping; hand the error to an AI.
- When to consider updating ports? : idk yet, When it traced the error to this port and the library is old as heck, or maybe just adjust dependency version, then check compatibility? lightwork.