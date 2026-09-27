# CLAUDE.md — House Rules

Random Dance combiner: reads a song list from a Google Sheet, downloads the YouTube videos, and combines the given time ranges into one long video or audio file with countdowns in between. Maintained across student generations, so clarity beats cleverness.

## Current phase

**SLICE 2 — speed**, branch `slice-2-speed`. No port changes expected; if one turns out to be needed, propose it and stop.

Scope:

1. **Look up each video only once.** Today each song's info is fetched twice: once while building the manifest, once again at download (about 2 s extra per song). The yt-dlp adapter should remember what it looked up and reuse it when downloading. This stays inside the adapter; the core and the port don't change. If remembered info can go stale or fail (e.g. expired download links), fall back to a fresh lookup and record when that happens.
2. **Run the manifest look-ups in parallel**, like downloads. Use `max_parallel_downloads` as the limit, so no new config key. Look-ups get the same retry policy as downloads (`max_retries`).
   - Results, row errors and warnings must still be **reported in sheet order**, even though they're checked out of order.
3. **Progress during look-ups.** Emit a progress event per row (e.g. "checking 12/40"), so a long list doesn't look frozen. The future GUI will show these.
4. **Long lists: measure first, then stop and report.** SPEC §6 says very long video lists are rendered in chunks and joined (the hybrid method in TECH §10), but this isn't built yet. Before building anything, render a long list in one pass (at least 60 songs; reusing cached songs with different time ranges is fine) and report time, memory use, and whether it succeeded. **Then stop.** The maintainer decides whether chunking is needed.

Acceptance:

1. **Single lookup:** in a live run, the log shows each song's info fetched once. Report the time saved per song.
2. **Parallel look-ups:** measure the manifest stage one-at-a-time vs in parallel, on the live sheet and on a longer list of at least 10 different videos (a local CSV built from videos already used in the spike is fine). Report both.
   - An offline test (fake media source, with delays and some failing rows) checks that the results come out in sheet order, with the right row errors on the right rows.
3. **Progress:** the console shows progress during look-ups, and an offline test checks one event per row.
4. **Long-list measurement** reported as above. No chunking code yet.
5. **No regressions:** all tests pass; one live audio and one live video run succeed against the sheet, with output length matching the plan; end-to-end time is no worse than slice 1.

How every slice works:
1. Work only on the slice's branch, created from an up-to-date `main`.
2. If the slice needs a **new port or a changed port signature**, propose it first and stop until it's approved. Otherwise, build directly.
3. Finish with the report below. The maintainer reviews, revisits the spec, and merges.

## Read before working

1. `docs/SPEC.md` — what and why. Owned by the maintainer.
2. `docs/ARCH.md` — architecture notes.
3. `docs/TECH.md` — how: tested recipes, quirks, measured numbers. **Reuse these recipes instead of rediscovering them.**
4. `docs/HANDOFF.md` — gotchas for successors.

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