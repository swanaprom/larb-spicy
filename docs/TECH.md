# Implementation Notes

The *how*. SPEC.md is the *what and why* and wins on any conflict.
Anything here that turns out to affect a goal, a port, or operator-facing behavior must be **promoted to [[SPEC.md]] by the maintainer** — never decided here.

Status tags: **[known]** confirmed by reasoning/docs · **[verify]** needs checking in practice · **[found]** confirmed by running it (add date).

---

## 1. Spike questions (answer these first)

Record answers in §9 Findings log, then update the relevant section below.

- [ ] Can trim + mirror + crossfade (`xfade` / `acrossfade`) + countdown insertion be done in **one FFmpeg pass**? What inputs must be known up front (clip durations?)
- [ ] Download strategy: full-song download + FFmpeg trim (current spec choice) vs. yt-dlp section download (`--download-sections` + `--force-keyframes-at-cuts`, recommended in an earlier fact-check for a 300–400 video pipeline). Compare speed and trim accuracy.
- [ ] Does current yt-dlp need a JS runtime (Deno) for YouTube? Test without it first.
- [ ] `static-ffmpeg`: first-use download behavior, time, size, where binaries land.
- [ ] Audio-only mode: which output format/codec, and does `acrossfade` behave the same?
- [ ] Rough efficiency baseline: minutes for N songs on this machine (feeds [[SPEC]] §2).

## 2. Environment

- A venv is a folder of libraries pointing to **one specific installed Python**. It isolates libraries, not Python. Updating Python does not update an existing venv; the venv keeps pointing at the old interpreter (or breaks if it was uninstalled). **The venv is disposable — rebuild, never repair.** [known]
- Finding Python: Windows `py -0` lists installed versions, `py -3.12` selects one. Linux/Mac: try `python3.13`, `python3.12`, `python3.11`. [known]
- Supported range is read from one file by both scripts. File name: TBD.
- yt-dlp update: `pip install -U yt-dlp` inside the venv. **Not** `yt-dlp -U` (that's for the standalone binary). On no internet: warn and continue. [known]
- yt-dlp drops Python versions once they reach end-of-life; when it refuses to install, bump the Python range (see HANDOFF.md recipe). [known]
- Installing system tools: after `winget` (Windows) or `brew` (Mac), a **new terminal** is usually needed before the tool is on PATH. On Linux, print the `sudo apt ...` command rather than running it. [known]
- Linux: tkinter may be a separate package (`python3-tk`); `setup_once` checks for it. [known]

## 3. FFmpeg

**Source — `static-ffmpeg` (pinned)**
- Binaries are fetched on **first use**, not at `pip install`. `setup_once` must trigger the download deliberately, or the first real run stalls. [known]
- Get the path explicitly: `static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()` → `(ffmpeg, ffprobe)`. Prefer this over `add_paths()` (which modifies PATH). [verify]
- Binaries live inside the venv's site-packages → **a venv rebuild re-downloads them.** [verify]
- Hosted by a single maintainer's GitHub repo. If the fetch fails, fall back to system FFmpeg. [known]
- Hardware-accelerated encoding (GPU) availability in these builds: unknown, not needed for now. [verify if ever relevant]

**Resolution order**
- `setup_once`: static-ffmpeg download → else system FFmpeg → else prompt operator to install.
- `run`: static → system → else stop with "run setup_once again". No downloading or prompting in `run`.
- System FFmpeg must be **≥ 4.3** (`xfade` was added in 4.3). Older = treat as not found. [known]
- Log at every run start: which FFmpeg (static/system), its version, and the yt-dlp version.

**Invocation helper (single module)**
- `subprocess` with an argument list (never a shell string).
- Binary path is element 0, kept separate from the arguments, so static↔system swap touches nothing else.
- Stream stderr/stdout into the logger; raise a project error type on non-zero exit.
- Always log the exact command, so it can be copy-pasted into a terminal to reproduce.
- Wrapper library `ffmpeg-python` rejected (unmaintained, awkward for multi-input filter graphs).

## 4. Sheet access (CSV export URL)

- A non-public sheet returns an **HTML sign-in page with a success status**, not an HTTP error. Check the response is actually CSV (e.g. body doesn't start with `<`, sensible content type) before parsing; abort with "sheet isn't publicly viewable". [known]
- Special-character / encoding handling already solved in the prototype script — port it over **with a comment explaining why it exists**, so nobody deletes it as unnecessary. [found — prototype]
- Local CSV file path is the fallback input (SPEC §9 stage 2).

## 5. Config (TOML)

- Read: `tomllib` (stdlib, 3.11+). Write: `tomli-w` (pinned). [known]
- Written once per run (at Run), after whole-config validation. Atomic write: write to a temp file **in the same directory**, then `os.replace()` onto `config.toml`. [known]
- TOML writers drop comments and may reorder keys → comments live only in `config/example.toml`. [known]
- Unsaved edits on GUI close: save or prompt (see SPEC §7).

## 6. GUI (Tkinter)

- Long work runs on a **background thread**. Tkinter widgets must only be touched from the main thread. [known]
- Pattern: worker puts log events on a `queue.Queue`; main thread drains it via `root.after(...)` polling. [known]
- Styling goal is guidance, not decoration: colors/fonts via `ttk` styles and Text-widget tags (e.g. ERROR red bold, WARNING amber, INFO default).

## 7. Output files

- Filename `{date}_{time}` — **no `:` in the time** (illegal in Windows filenames). Use e.g. `2026-09-25_143012`. [known]
- If the file already exists (two runs in the same second): auto-suffix, never overwrite. [decide in slice]

## 8. Repo housekeeping

- `.gitignore` (write before first commit): `workspace/`, `config.toml`, credentials (`*.json` key files), `.venv/`, `CLAUDE.local.md`, `__pycache__/`, `.obsidian/workspace*.json`.
- `docs/` is also an Obsidian vault. Use **standard Markdown links**, not `[[wikilinks]]` (they don't render on GitHub). Keep attachments small; no media in the vault.

## 9. Findings log

Newest first. Date · what was tried · result · where it's now documented.

| Date | Finding | Result | Documented in |
| ---- | ------- | ------ | ------------- |
|      |         |        |               |