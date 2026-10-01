# CLAUDE.md — House Rules

Random Dance combiner: reads a song list from a Google Sheet, downloads the YouTube videos, and combines the given time ranges into one long video or audio file with countdowns in between. Maintained across student generations, so clarity beats cleverness.

## Current phase

**SLICE 7 — Est. Length and remembered inputs**, branch `slice-7-length-memory`. Two operator conveniences from HANDOFF's upgrade list. If either needs a port change, propose it and stop.

Scope:

1. **Est. Length** (GUI.md 3.2). The button becomes usable when the Sheet field is filled and no run is going.
   - **What it does:** read the sheet with the window's current row range, mode, countdown and crossfade, and calculate the output length **without contacting YouTube**.
     - Songs already cached for this mode: length measured from the file (exact).
     - Other songs: from their time ranges, padding included.
     - The countdown: measured if cached. If it's a URL that isn't cached, **one** look-up for its length is allowed.
   - **One source of truth:** the estimate must use the **same planning code** as a real run (padding, per-join crossfades, the end fade-out), not a second copy of the length maths.
   - **Result: a pop-up**, e.g. "Estimated: 1 hour 46 min 20 s".
     - If rows were left out (broken time range), add one line: "2 rows left out (time range can't be read)".
     - Also log the result as one INFO line, so it's still visible after the pop-up closes.
   - **Known limit, accepted:** a video deleted from YouTube still counts in the estimate; the run catches it at download time.
2. **Remember the last inputs.**
   - **What:** the Sheet field and the Countdown field. **Not** the row range, deliberately: a remembered range could silently cut the next run short.
   - **When:** saved when Run is pressed; filled in when the window opens.
   - **Where:** `config/last_inputs.toml`, gitignored, separate from `config.toml`. Clear cache never touches it.
   - **If it's missing, unreadable or points to a file that's gone:** the fields simply start empty or as remembered. No error, no crash. The usual checks happen on Run.
3. **Docs:**
   - GUI.md: 3.2 (Est. Length is no longer "Coming later"), 1.1 and 1.4 (remembered).
   - HANDOFF: take Est. Length and "remember the last inputs" off the upgrade list, and note what remains of "remember each video's length" (only uncached rows still need YouTube).
   - TECH: anything learned.

Acceptance:

1. **Accuracy:**
   - Offline: for a fully cached fixture list, the estimate equals the length the real run plans (within 0.05 s). With uncached songs (fake source), it's within about 1 s per uncached song.
   - Live: estimate, then run, on the sheet in both modes; report estimate vs actual. A fully cached rerun should match.
2. **No YouTube:** an offline test with a fake media source that counts calls: the estimate makes zero look-ups when the countdown is cached, and exactly one when it isn't.
3. **The button:** disabled with an empty Sheet field and during a run. The pop-up's wording and the left-out-rows line are covered by a GUI-state test.
4. **Remembered inputs** (offline tests):
   - saved on Run, filled in on open;
   - the row range is never saved;
   - Clear cache leaves the file alone;
   - a missing or corrupt file gives empty fields, with no error.
5. **Maintainer checks** (list the steps): click Est. Length on the live sheet and compare it with the real run's length. Close and reopen the window: Sheet and Countdown are filled in, rows are empty.
6. **No regressions:** all tests pass (report the suite time); the terminal path works; live audio and video runs succeed.

How every slice works:
1. Work only on the slice's branch, created from an up-to-date `main`.
2. If the slice needs a **new port or a changed port signature**, propose it and stop until it's approved. Otherwise, build directly.
3. Finish with the report below. The maintainer reviews, revisits the spec, and merges.

## Read before working

1. `docs/SPEC.md` — what and why. Owned by the maintainer.
2. `docs/ARCH.md` — architecture notes.
3. `docs/TECH.md` — how: tested recipes, quirks, measured numbers. **Reuse these recipes instead of rediscovering them.**
4. `docs/HANDOFF.md` — gotchas for successors.
5. `docs/GUI.md` — gui plan. Owned by the maintainer.

## Authority

- **SPEC.md wins** over every other document and over your own judgment.
- If your work conflicts with the spec, or a finding would change a goal, a port, or operator-facing behavior: **stop and flag it**. Do not edit SPEC.md. The maintainer decides whether the spec or the code changes.
- Record new technical findings in `docs/TECH.md` as you go, including dead ends and why they failed.

## Git

- Never commit to `main`. Never merge. Work only on the branch named in "Current phase".
- Small, focused commits. **Commit doc changes separately from code changes.**
- Don't push unless asked.

## Architecture (hexagonal) — the most important rules

The five ports and their adapters are listed in SPEC §5: `SettingsStore`, `SongListSource`, `MediaSource`, `MediaProcessor`, `EventSink`.

- **Core must not import anything from adapters, the GUI, or third-party tools** (yt-dlp, static-ffmpeg, tkinter, HTTP libraries, tomli-w). If core needs it, it goes through a port.
- **Ports belong to the core** and live with the core, not with the adapters.
- **Ports speak the core's language, not a tool's.** Test: could this port be implemented with a completely different tool? If it mentions anything only yt-dlp / FFmpeg / Google has, it's leaking.
- **Errors crossing a port are the project's own error types** (under `LarbError`), never a library's exceptions.
- **Never change a port signature without asking.** New ports are proposed first, approved, then implemented.
- The GUI never calls yt-dlp or FFmpeg directly; it only talks to the core.
- Sheet column names are known only to the sheet adapter (via `[sheet.columns]`). The core sees manifest fields, never column names.

## Settings: configurable, file-only, hard-coded

SPEC §7 sorts every setting into one of three kinds. Respect the sorting:
- **File-only** keys must never appear in the GUI.
- **Hard-coded** behavior (audio normalization, output video format, audio-only `.mp3`, download codec preference, the end fade-out) must not be turned into settings.
- Don't add, rename, or remove config keys without asking.

## Do not change without asking

- The TOML config schema (`config/example.toml`) and the `[sheet.columns]` mapping — the dance group depends on these.
- Port signatures.
- Pinned versions in `requirements.txt` and the supported Python range.
- yt-dlp must stay **unpinned** (always latest). Do not pin it, and do not unpin anything else.

## Files and data

Where the **program** writes:
- By default, everything generated goes inside `workspace/` (cache, output, temporary files).
- The live settings file is `config/config.toml`. It deliberately lives outside `workspace/`, so deleting `workspace/` never loses settings.
- The operator may choose output and cache folders anywhere (SPEC §7). Respect that choice.

Where **you** write during development:
- Your own test runs stay inside `workspace/` and `config/config.toml`. Restore `config/config.toml` to how you found it when you're done.
- Don't delete folders in `workspace/` that you didn't create. The maintainer keeps test material there (e.g. `test_media/`, `moviepy_table/`).
- `tests/fixtures/` holds only **tiny** clips (seconds long). Anything larger belongs in `workspace/`.
- Never commit media outside `tests/fixtures/`, or `workspace/`, `config/config.toml`, credentials, `.venv/`, or `CLAUDE.local.md`.

## FFmpeg and yt-dlp

- Every FFmpeg call goes through the single helper module inside the FFmpeg adapter. No ad-hoc `subprocess` calls elsewhere.
- The FFmpeg binary path is always passed explicitly, separate from the argument list. Never rely on `ffmpeg` being on PATH — a different system FFmpeg exists on the maintainer's PC.
- FFmpeg must be **7.1 or newer**; there is no code path for older versions.
- Follow the yt-dlp and FFmpeg recipes in `docs/TECH.md` (§3, §9, §10). They were measured; deviate only with a reason, and record it.

## Running and testing

- Run the program from the repo root with `src` on the path. PowerShell: `$env:PYTHONPATH="src"`; Command Prompt: `set PYTHONPATH=src`; Linux/Mac: `export PYTHONPATH=src`. Then `python -m larb <sheet> [--countdown <file or URL>] [--rows first-last]`.
- Run the tests with `python -m unittest` (standard library; nothing extra to install).
- Tests run **fully offline**, from `tests/fixtures/` only. No downloading, no YouTube calls, no sheet fetch. They check output **length**, not just that a file exists.
- All tests must pass before you report a slice as done. Add tests for new behavior where it can be tested offline.

## Done means

- The acceptance condition given with the task is met.
- All tests pass.
- Don't claim something works unless you ran it. Say so if you couldn't.

## How to report

End every task with:
1. **What changed** (files, commits).
2. **What was verified**, and how.
3. **What was not verified.**
4. **Decisions for the maintainer** — anything you flagged instead of deciding.
5. **Spec mismatches** — any SPEC.md section that no longer matches the code, so the maintainer can revisit it before merging.