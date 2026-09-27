# CLAUDE.md — House Rules

Random Dance combiner: reads a song list from a Google Sheet, downloads the YouTube videos, and combines the given time ranges into one long video or audio file with countdowns in between. Maintained across student generations, so clarity beats cleverness.

## Current phase

**SLICE 1 — polish**, branch `slice-1-polish`. No new ports expected; if one turns out to be needed, propose it and stop.

Scope, five small features:

1. **Countdown from a URL.** `--countdown` accepts a local file *or* a YouTube URL. Without `--countdown`, use `countdown.default_urls[0]`, then `countdown.default_files[0]`; if none, stop with a clear message.
   A countdown URL goes through the same MediaSource as songs: looked up, downloaded with the same retry policy, cached with the same key (`<id>_audio` / `<id>_v<height>`), and normalized like songs. Countdowns are still never padded or mirrored.
   If the countdown can't be found or downloaded after retries, **abort the run** (a compilation can't be built without it).
2. **End fade-out.** The last song fades out to silence and to black (video) over the crossfade duration, ending exactly at the end of the output. Hard-coded, no setting. The output length must not change.
3. **Row range.** `--rows <first>-<last>` limits the run to those rows, numbered as shown in Google Sheets (the header is row 1, so the first song is row 2). Without `--rows`, all rows are used. A range that is backwards or outside the sheet stops the run with a clear message.
4. **Log file.** Every run writes its log events to `workspace/logs/<date>_<time>.log`, the same events as the console. Only the 5 newest log files are kept; older ones are deleted at the start of a run.
5. **Cache-clear prompt.** After a successful run in an interactive terminal, ask "Clear the download cache? [y/N]". The default (Enter) is No. When not interactive (e.g. in tests), don't ask.

Acceptance:

1. **Countdown URL:** a live run with the countdown URL given in the task works end to end. A second identical run downloads nothing, the countdown included. Also verify that `default_urls` is used when `--countdown` is omitted.
2. **Fade-out:** in the live video and audio outputs, the maintainer sees and hears the ending fade out. Also add an offline test that checks the end of the output is (near) silent and (near) black, and that the length still matches the plan.
3. **Row range:** a live run with `--rows 2-3` contains only those two songs (plus countdowns). An offline test covers a backwards range and an out-of-sheet range.
4. **Log file:** an offline test runs the log rotation with more than 5 existing logs and checks that exactly the 5 newest remain.
5. **Cache prompt:** it appears after a live run and No keeps the cache. The tests never block on it.
6. **All tests pass offline**, and one live audio run plus one live video run succeed against the sheet.

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

- Run the program from the repo root with `src` on the path: `set PYTHONPATH=src` (Windows) or `export PYTHONPATH=src`, then `python -m larb <sheet> --countdown <file>`.
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