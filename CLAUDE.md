# CLAUDE.md — House Rules

Random Dance combiner: reads a song list from a Google Sheet, downloads the YouTube videos, and combines the given time ranges into one long video or audio file with countdowns in between. Maintained across student generations, so clarity beats cleverness.

## Current phase

**SLICE 6 — reliability**, branch `slice-6-reliability`. Fixes found in real use on a native Ubuntu 24.04 PC (fast network) and planned in SPEC §9 ("Planned (slice 6)" notes in stages 3, 4, 5, 7) and GUI.md 2.3. If any item needs a port change, propose it and stop.

Scope, in this order:

1. **Record the Ubuntu findings in TECH.md first** (maintainer's test, 2026-09):
   - **The PC:** a real (not VM) Ubuntu 24.04 PC. Python 3.12.4 was already installed (in range).
   - **tkinter** was missing; setup's printed command fixed it on the first try.
   - **The window icon** doesn't show (normal on that desktop).
   - **Open file** failed until a media player was installed (the console said "no media player found"); after installing VLC it worked.
   - **Output:** audio and mirrored video both worked. 5 songs took well under a minute on a fast network.
   - **A cached countdown still triggered the bot check** during look-ups, and rows were skipped after their retries ran out. Re-running a few minutes later recovered the missing song.
2. **Countdown without a picture, in video mode.** Show a **black screen** for its length, with its sound, and one warning per run. Nothing else is drawn. Apply the same rule to any clip without a picture, with a row warning for songs.
3. **Render progress.** The FFmpeg adapter reports how much of the planned output has been written, as plain done/total numbers through the existing progress events.
   - **GUI:** a filling bar with "Rendering 63%", for audio and video. Any step without numbers (e.g. between video parts, the final join) shows the sweeping bar. The bar is never empty and still.
   - **Terminal:** one progress line every 10%, no more.
4. **Cache-aware checking** (SPEC §9 stage 4).
   - A row whose file **for this run's mode** is cached skips the YouTube look-up; its length is measured from the file. The countdown too.
   - If only the other mode is cached, it's still looked up (the download needs it).
   - All existing length rules still apply to measured lengths: trim to fit within ~1 s with a warning, otherwise a row error.
5. **Smarter retries** (SPEC §9 stage 5). **Measure first, briefly:**
   - Try a few 403 retry wait patterns on the maintainer's **home** connection (never a company network), time-boxed. Stop at the first bot check, and record what you saw in TECH.md.
   - Then build:
     - **403:** waits that grow each attempt and are slightly randomised, so parallel retries don't arrive together.
     - **Bot check / HTTP 429:** start no new look-ups or downloads, let running ones end, keep everything cached, and stop the run with a clear message ("YouTube is limiting this connection. Wait a while, then run again; finished songs stay cached."). In the GUI that's the aborted-run pop-up.
     - All waits stay interruptible by Stop.
6. **Open file / Open folder failing:** show a pop-up with the reason (e.g. "No app is set to open .mp4 files. Install a media player, or use Open folder."), and log it as a warning.
7. **Docs:** HANDOFF's rate-limit and Open file sections describe the new behaviour. TECH.md gets the measurements and quirks.

Acceptance:

1. **Black screen:** an offline test with an `.mp3` countdown in video mode gives a valid output of the planned length, black during the countdowns, and exactly one warning. The maintainer views it.
2. **Render progress:**
   - An offline test checks the render's progress events rise to their total.
   - A GUI-state test checks the label shows the percentage, and that the bar sweeps when there are no numbers.
   - Live audio and video runs show the bar filling, with no still, empty bar between parts. The maintainer watches.
3. **Cache-aware checking:**
   - An offline test with a fake media source that counts look-ups: cached rows and a cached countdown make **zero** look-ups; a row cached only in the other mode is still looked up; a cached row whose end time is past its real length is still trimmed or rejected by the existing rules.
   - Live: a second identical run makes no YouTube look-ups (shown in the log).
4. **Retries:**
   - The measurement is reported.
   - Offline tests (with a controllable clock and randomness) check that 403 waits grow and vary.
   - A simulated bot check stops the run cleanly: no new requests start, cached songs stay, and the message is clear.
   - Stop during a retry wait ends promptly.
5. **Open file failure:** an offline test simulates a missing app and checks for the pop-up and the warning.
6. **No regressions:** all tests pass; the terminal path works; live audio and video runs succeed with lengths matching.

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