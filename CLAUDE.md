# CLAUDE.md — House Rules

Random Dance combiner: reads a song list from a Google Sheet, downloads the YouTube videos, and combines the given time ranges into one long video or audio file with countdowns in between. Maintained across student generations, so clarity beats cleverness.

## Current phase

**SLICE 4 — setup and run scripts**, branch `slice-4-setup-run`. The program itself shouldn't change; if it needs to, stop and flag it. No port changes expected.

Goal: a successor clones the repo, runs one setup script, then one run script, and gets an output, without knowing Python. Follow SPEC §16 and TECH §2–§3.

Scope:

1. **Keep the shell scripts thin.** `setup_once.bat` / `setup_once.sh` and `run.bat` / `run.sh` only find a suitable Python, then hand over to **one shared Python script** (e.g. `tools/env_setup.py`) that does the rest. The logic lives in one place, not in two shell languages.
2. **Supported Python range** in one plain file at the repo root, `python-range.txt`, containing `3.11-3.13`. Both scripts read it; nothing else hard-codes the range.
3. **`setup_once`:**
   - Find a Python in the range (Windows: `py -0` / `py -3.x`; Linux/Mac: `python3.13`, `python3.12`, `python3.11`).
   - If none is found, say which version to get and that it **installs alongside** the existing Python, with nothing to uninstall. Then **ask** before installing: `winget` on Windows, `brew` on Mac. On Linux, print the command instead. After an install, tell the user to open a new terminal and run setup again.
   - Build `.venv` with that Python, install `requirements.txt`, then `pip install -U yt-dlp`.
   - Trigger the `static-ffmpeg` download now (about 45 s, 200 MB the first time), so the first real run doesn't stall. If that fails: accept a system FFmpeg 7.1 or newer; otherwise **ask** before installing one (or print the command on Linux).
   - On Linux, check that tkinter is available (`python3-tk`) and print the install command if not. The GUI will need it.
   - Running it again is safe and fast: nothing is rebuilt unless something is missing or out of range.
4. **`run`:**
   - If `.venv` is missing, or its Python is outside the range, rebuild it automatically.
   - `pip install -U yt-dlp`. If there's no internet, warn and continue with the installed version.
   - Set `src` on the path and UTF-8 output, so Thai titles print correctly in the console, then start `python -m larb`, passing through any arguments.
   - With no arguments (e.g. double-clicked on Windows), ask for the sheet URL, and keep the window open at the end so the operator can read the result.
5. **Never touch the system:** no system-wide `pip install`, no `sudo`, no permanent PATH changes. Anything installed outside `.venv` is asked about first.
6. **Docs:** the README gets the three-step "clone, setup, run" instructions. The HANDOFF terminal section is replaced by the scripts.

Acceptance:

1. **Fresh clone, Windows:** clone into a new folder **whose path contains a space**. Run `setup_once.bat`, then `run.bat <sheet URL>`: it produces an output. Report the setup time.
2. **Setup again:** `setup_once.bat` a second time finishes quickly, without rebuilding.
3. **Wrong Python in the venv:** the maintainer has Python 3.14 installed. Build `.venv` with 3.14 by hand, then run `run.bat`: it detects the problem, rebuilds with 3.12, and succeeds.
4. **No Python in range** (simulated, e.g. an environment variable that overrides the range to one nothing satisfies): the message and the install offer appear, and **nothing installs without a yes**.
5. **FFmpeg fallback** (simulated `static-ffmpeg` failure): setup finds a system FFmpeg if it's 7.1 or newer, or offers an install. Report what this PC's system FFmpeg version is.
6. **No internet at run** (simulated): the yt-dlp update warns, and the run continues.
7. **Linux via WSL:** a fresh clone, `setup_once.sh`, then `run.sh` gives an audio output. Report what the tkinter check said.
8. **Maintainer check (report the steps for me):** double-click `run.bat`, paste the sheet URL, get an output, with Thai titles readable in the window and the window staying open.
9. **All tests pass**, and the program's own behavior is unchanged.

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