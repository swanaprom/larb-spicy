# Implementation Notes

The *how*. SPEC.md is the *what and why* and wins on any conflict.
Anything here that turns out to affect a goal, a port, or operator-facing behavior must be **promoted to [[SPEC.md]] by the maintainer** — never decided here.

Status tags: **[known]** confirmed by reasoning/docs · **[verify]** needs checking in practice · **[found]** confirmed by running it (add date).

---

## 1. Spike questions (answer these first)

Record answers in §11 Findings log, then update the relevant section below.

- [x] Can trim + mirror + crossfade (`xfade` / `acrossfade`) + countdown insertion be done in **one FFmpeg pass**? What inputs must be known up front (clip durations?) → **Yes.** Durations of every clip must be known up front (for `xfade` offsets); see §10.
- [x] Download strategy: full-song download + FFmpeg trim (current spec choice) vs. yt-dlp section download (`--download-sections` + `--force-keyframes-at-cuts`, recommended in an earlier fact-check for a 300–400 video pipeline). Compare speed and trim accuracy. → **Full download + trim wins** on speed and accuracy; see §9.
- [x] Does current yt-dlp need a JS runtime (Deno) for YouTube? Test without it first. → **Not today, but deprecated** (yt-dlp warns); see §9. Maintainer decision flagged.
- [x] `static-ffmpeg`: first-use download behavior, time, size, where binaries land. → 43 s, ~198 MB, inside the venv; see §3.
- [x] Audio-only mode: which output format/codec, and does `acrossfade` behave the same? → Same graph minus video; MP3 (`libmp3lame`) or M4A (`aac`) both exact; see §10.
- [x] Rough efficiency baseline: minutes for N songs on this machine (feeds [[SPEC]] §2). → 10 songs: audio ~12 s render, video ~2 min render (H.264 source); see §10.

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
- Binaries are fetched on **first use**, not at `pip install`. `setup_once` must trigger the download deliberately, or the first real run stalls. [found 2026-09-26: first call took **43 s** on this connection; later calls 0.4 s]
- Get the path explicitly: `static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()` → `(ffmpeg, ffprobe)`. Prefer this over `add_paths()` (which modifies PATH). [found 2026-09-26: returns absolute paths, PATH untouched]
- Binaries live inside the venv's site-packages → **a venv rebuild re-downloads them.** [found 2026-09-26: `.venv/Lib/site-packages/static_ffmpeg/bin/win32/{ffmpeg,ffprobe}.exe`, ~99 MB each, **~198 MB total**; the zip is deleted after extraction; an `installed.crumb` file marks completion]
- `static_ffmpeg==3.0` on Windows fetches **FFmpeg 8.0.1** (gyan.dev *essentials* build) from `github.com/zackees/ffmpeg_bins`. Includes `xfade`, `acrossfade`, `libx264`, `libmp3lame`, `aac`. [found 2026-09-26]
- It prints its download progress to stdout — the helper should capture/redirect that into the logger rather than let it leak. [found 2026-09-26]
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
- Always log the exact command, so it can be copy-pasted into a terminal to reproduce. (`subprocess.list2cmdline(cmd)` gives a Windows-pasteable string.)
- Wrapper library `ffmpeg-python` rejected (unmaintained, awkward for multi-input filter graphs).
- Filenames with Thai text and `[]()&@!^%$` pass through fine as list elements — no quoting/escaping needed. [found 2026-09-26]
- Decode FFmpeg output as UTF-8 with `errors="replace"`; the Windows locale here is cp874 (Thai), so the default text decoding is wrong. [found 2026-09-26]
- **Put the filter graph in a file**, not on the command line: `-/filter_complex <path>` (FFmpeg 7.1+ syntax; `-filter_complex_script` is the older, deprecated form). The graph grows ~500 chars per song; Windows' 32 767-char command-line limit is hit around **50 songs**. [found 2026-09-26: file form works in 8.0.1]

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

## 9. Download (yt-dlp)

Measured 2026-09-26 with yt-dlp 2026.08.19, one song (`oKBwWQI-IoI`, 162 s), clip 0:27–1:04 (37 s). Scripts: `scratch/spike_download.py`.

| Strategy | Wall time | Clip length (want 37.000 s) |
| --- | --- | --- |
| A. Full audio download + FFmpeg trim | 4.3 s + 1.4 s | **37.000** |
| B. `--download-sections` audio | 3.4 s | 43.980 ✗ (starts ~7 s early) |
| C. Full video ≤720p + FFmpeg trim | 11.5 s + 9.5 s | **37.000** |
| D. `--download-sections` video | 22.6 s | 43.980 ✗ (starts ~7 s early) |
| E. `--download-sections` + `--force-keyframes-at-cuts` | 87.7 s | 37.008 |

- **Full download + trim is the right call** (keeps SPEC §3). Plain sections snap to a fragment/keyframe boundary before the start: verified by frame comparison that 7 s into clip D equals 0:27 in the full video. Keyframe forcing fixes accuracy but is ~4–8× slower than a full download, and it caches nothing reusable. The trim itself happens inside the render pass anyway (§10), so no separate trim step is needed. [found]
- **JS runtime:** without Deno, downloads work and give the same 44 formats as with Node enabled. yt-dlp prints `WARNING: No supported JavaScript runtime could be found … YouTube extraction without a JS runtime has been deprecated, and some formats may be missing`. Only **Deno** is enabled by default; Node on PATH is ignored unless `--js-runtimes node` is passed. [found] → maintainer decision flagged (see §10 open flags).
- **Default format is huge:** `bv*+ba` picked format 401 (2160p AV1), 150 MB for one song. Cap resolution, e.g. `-S "vcodec:h264,res:720,acodec:m4a"` (a sort, so it still falls back when no H.264 exists). [found]
- **Prefer H.264 sources:** YouTube's default 720p pick was AV1, and software AV1 decoding made the render **2.4× slower** (§10). [found]
- Always pass `--ffmpeg-location <static bin dir>`: otherwise yt-dlp merges with whatever `ffmpeg` is on PATH (a system FFmpeg exists on this PC). [found]
- Pass `--no-playlist`: sheet URLs contain `&list=RDMM…`. [found]
- Bad IDs fail loudly (exit 1, specific message): truncated ID → `Incomplete YouTube ID … looks truncated`; well-formed but missing → `This video is unavailable`. Good for row errors. [found]
- Windows console locale here is cp874 → set `PYTHONIOENCODING=utf-8` (or use the Python API) when capturing yt-dlp output. [found]

## 10. Rendering (one FFmpeg pass)

Scripts: `scratch/spike_one_pass.py`, `spike_edge.py`, `spike_baseline.py`. FFmpeg 8.0.1.

**Recipe** (sequence: countdown → song → countdown → song …, crossfade `d` at every join):
1. One input per segment: `-ss <start> -t <end-start> -i <file>` (input-side seek; accurate because we re-encode, and avoids decoding the whole song). The same countdown file can simply be added as an input again.
2. Normalize every segment, because inputs don't match (fixtures: 44.1k vs 48k audio; 1280×720@29.97 vs 640×360@25 video):
   - audio: `aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS`
   - video: `scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[,hflip],setpts=PTS-STARTPTS`
   - Mirror = `hflip`, applied to song segments only, not to countdowns.
3. Chain joins: `acrossfade=d=D` (needs no durations) and `xfade=transition=fade:duration=D:offset=L-D`, where `L` = output length so far (`L += dur_i - D`). **`xfade` offsets mean every segment's duration must be known before building the graph.**
4. Output length = Σ durations − D × (joins). Matched to the millisecond in every test; A/V ended within one frame (no drift across 20 segments). [found]

- Verified visually: a frame mid-join shows the countdown blending into the song; the mirrored frame is a horizontal flip of the source. [found]
- **Audio-only** = the same graph without the video half. `libmp3lame` (.mp3) and `aac` (.m4a) both produce exact lengths; MP3 encoding was faster (1.5 s vs 2.6 s for 68 s of output). [found]
- ⚠ **Silent corruption on overrun:** if `end_time` is past the real file length (asked 1–20 s of a 7.27 s file), FFmpeg **exits 0** but the output is wrong (audio 10.6 s, video 6.3 s, the next segment's video is missing). Every song must be probed (`ffprobe` duration) and `end_time <= duration` validated **before** rendering. This is Goal 1 territory. [found] → flagged.

**Efficiency baseline** (i5-6400, 4 cores, 10 songs × 37 s + 10 countdowns = 6.7 min output, one pass):

| Mode | Render time |
| --- | --- |
| Audio-only, MP3 192k | **11.8 s** |
| Video 720p30, x264 `veryfast` crf 23, **AV1** source | 288 s |
| Video 720p30, x264 `veryfast` crf 23, **H.264** source | **118 s** |

Plus downloads: ~4 s/song for audio, ~11 s/song for 720p video on this connection. The moviepy prototype wasn't timed side by side, so the SPEC §2 target number is still the maintainer's to set. [found]

**Open flags for the maintainer** (not decided here, per CLAUDE.md):
1. **Sheet columns vs the prototype parser:** the current sheet has `ชื่อเพลง, ศิลปิน, URLs, ช่วงเวลา, ผู้เสนอเพลง + ชั้นปี, Mirrored แล้ว, หมายเหตุ`. URL is at index 2 and time at index 3, but `scratch/test_parser.py` expects 3 and 4, so every row gets dropped. The sheet also has a per-row "Mirrored แล้ว" column, which the spec doesn't mention (the spec has only the global `processing.mirror`).
2. **New row error:** "end time is past the song's length". It can only be detected after download, so it doesn't fit the manifest-stage-only validation in SPEC §8/§9.
3. **Download format/quality config** (SPEC §7 TODO): suggest a 720p cap with an H.264 preference.
4. **Deno:** works without it today, but it's deprecated upstream. Install it in `setup_once` now, or wait until it breaks?

## 11. Findings log

Newest first. Date · what was tried · result · where it's now documented.

| Date | Finding | Result | Documented in |
| ---- | ------- | ------ | ------------- |
| 2026-09-26 | 10-song render baseline, AV1 vs H.264 source | audio 12 s; video 288 s → 118 s with H.264 | §10 |
| 2026-09-26 | `end_time` past file length | FFmpeg exits 0 with corrupt output; must probe first | §10 |
| 2026-09-26 | Long graphs on Windows | ~50-song cmd-line limit; `-/filter_complex file` works | §3 |
| 2026-09-26 | One-pass trim+mirror+crossfade+countdown, audio and video | works, exact durations, needs normalize + known durations | §10 |
| 2026-09-26 | Full download vs `--download-sections` (± keyframes) | full+trim fastest and exact; sections start ~7 s early; keyframes 88 s | §9 |
| 2026-09-26 | yt-dlp without JS runtime | works, same formats, deprecation warning; Node ignored by default | §9 |
| 2026-09-26 | New sheet vs prototype parser | column indices shifted → 0 rows parsed | §10 flags |
| 2026-09-26 | `static_ffmpeg==3.0` first use | 43 s, 198 MB in venv, FFmpeg 8.0.1, PATH untouched | §3 |