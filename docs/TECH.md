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
- Current sheet layout (2026-09): `ชื่อเพลง, ศิลปิน, URLs, ช่วงเวลา, ผู้เสนอเพลง + ชั้นปี, Mirrored แล้ว, หมายเหตุ` → URL index 2, time range index 3. People type stray spaces inside numbers (`1. 04`, `0.4 6-1:3 0`), so strip **all** whitespace before parsing a time range. The moviepy-era CSV used `HH:MM:SS` in separate start/end columns instead. [found 2026-09-26]

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
- **Node works as the JS runtime** (Deno not tested, on purpose): CLI `--js-runtimes node`, Python API `"js_runtimes": {"node": {}}`. The deprecation warning disappears, yt-dlp reports `JS runtimes: node-24.11.1`, and metadata and downloads work. The downloaded file is byte-for-byte the same length as without a runtime. [found 2026-09-26]
- **Default format is huge:** `bv*+ba` picked format 401 (2160p AV1), 150 MB for one song. Cap resolution, e.g. `-S "vcodec:h264,res:720,acodec:m4a"` (a sort, so it still falls back when no H.264 exists). [found]
- **720p cap confirmed** on both sheet songs with `format_sort = ["vcodec:h264", "res:720", "acodec:m4a"]`: Perfect Night → `136+140` (720p30 H.264 + AAC, 24 MB, 6.4 s); Drama → `298+140` (**720p60** H.264 + AAC, 68 MB, 19 s). 60 fps sources exist; the render normalizes to 30 fps anyway. [found 2026-09-26]

**Early length check (before downloading)** — `scratch/spike_length_check.py`, worked on attempt 1:
- `YoutubeDL.extract_info(url, download=False)` returns metadata only; `info["duration"]` is the video length. It takes **0.4–2.7 s per row**, with no media downloaded. That means an "end time past song length" row can be rejected at manifest validation, before any download. [found 2026-09-26]
- Caught correctly: synthetic `100–9999` on a 162 s video → error; unavailable ID → `DownloadError` with a readable message. [found]
- The same `info` dict can be handed to `ydl.process_ie_result(info, download=True)`, so each video's metadata is fetched only once. [found]
- ⚠ **`duration` is whole seconds, rounded** (metadata 217 vs real file 216.828 s; 162 vs 162.191). An end time within about 0.5 s of the end can pass the metadata check and still overrun the real file. **The early check doesn't replace the ffprobe check after download**; it only catches most bad rows early. [found]
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
- ⚠ **Silent corruption on overrun:** if `end_time` is past the real file length (asked 1–20 s of a 7.27 s file), FFmpeg **exits 0** but the output is wrong (audio 10.6 s, video 6.3 s, the next segment's video is missing). Every song must be probed (`ffprobe` duration) and `end_time <= duration` validated **before** rendering. This is Goal 1 territory. [found] → flagged. Two guards: the metadata check at manifest stage (§9), plus ffprobe of the cached file before rendering (the spike's `build()` now refuses the overrun). [found 2026-09-26]
- ⚠ **Output must be forced to `-pix_fmt yuv420p`.** With `format=yuv420p` only on the inputs, `xfade` negotiated **yuv444p**, and x264 then wrote `High 4:4:4 Predictive`. Windows' built-in players can't decode that ("encoding" error reported by the operator). Plain trims were fine because they never went through `xfade`. With `-pix_fmt yuv420p` on the output: profile `High`, yuv420p. Also map video before audio and add `-movflags +faststart`. [found 2026-09-26] (Operator-side playback of the fixed file not yet confirmed.)
- **Padding (±1 s around each song's range)**, clamped to the file: `start' = max(0, start−1)`, `end' = min(real_length, end+1)`. Countdowns aren't padded. Tested with real songs (27–64 → 26–65) and on a 7.274 s file asked 0–7.274 (clamps on both sides and still gives the exact length). [found 2026-09-26] Note the moviepy prototype did the same (`fade_duration` padding).

**Efficiency baseline** (i5-6400, 4 cores, 10 songs × 37 s + 10 countdowns = 6.7 min output, one pass):

| Mode | Render time |
| --- | --- |
| Audio-only, MP3 192k | **11.8 s** |
| Video 720p30, x264 `veryfast` crf 23, **AV1** source | 288 s |
| Video 720p30, x264 `veryfast` crf 23, **H.264** source | **118 s** |

Plus downloads: ~4 s/song for audio, ~11 s/song for 720p video on this connection. [found]

**vs the moviepy prototype** — same 5 rows (`workspace/moviepy_table/entry.csv` rows 1–5), same settings where they map (1 s padding, 1 s fades, no mirror, 5 parallel downloads, both .mp4 and .mp3 written). The prototype ran unmodified in its own venv under `workspace/spike/` (moviepy 2.2.1). Ours: `scratch/spike_vs_moviepy.py`.

| | moviepy prototype | this pipeline |
| --- | --- | --- |
| End-to-end wall time | **605 s** | **104 s** (download 49 s + video 50 s + mp3 5 s) |
| Video | 640×360 25 fps | 1280×720 30 fps |
| Video / audio length | 202.68 s / **177.71 s** ✗ | 202.70 s / 202.70 s |

- About **5.8× faster** end to end, at a higher resolution. The prototype log has no timestamps, so its download/render split is unknown. Its `format: "mp4"` pulls a slow fragmented stream (visible as `.part-FragN` files). [found 2026-09-26]
- Prototype defects seen (for the record, not to fix): the output size is taken from the first clip (the 640×360 countdown), so 720p songs are cropped or downscaled; the final audio is 25 s shorter than the video. [found]
- This is a baseline the maintainer can turn into the SPEC §2 target, e.g. "≤ 25 s per song end-to-end for 720p video on the reference PC". It's not set here.

**Long lists: chunk, then join** — `scratch/spike_chunks.py`. The graph-in-file (§3) already removes the command-line limit. Chunking is still useful to bound memory and per-run risk, and to resume after a crash. Three join methods were tried on the same songs (audio: 10 songs, chunks of 5; video: 6 songs, chunks of 3):

| Method | Video time (6 songs) | Result |
| --- | --- | --- |
| One pass (reference) | 71–75 s | exact |
| A. Render chunks, then **re-encode join** with the same crossfade at the seam | 70 + 63 = **133 s** | audio exact; video +0.023 s per seam (frame rounding); **second lossy encode** |
| B. Split **mid-countdown**, join with concat demuxer **`-c copy`** | 71 + 0.4 s | ✗ **9–19 ms dropout** at every seam (AAC encoder padding), +20 ms length per seam. The single-pass file has no dropout at the same point |
| C. **Hybrid**: video split mid-countdown **on a frame boundary** and copy-joined; audio rendered in **one pass**; then mux (`-c copy`) | 72.5 + 0.3 + 9.8 + 0.3 = **83 s** | ✅ same frame count as one pass (8281), stream lengths identical to one pass, seam frames identical to one pass (checked visually) |

- **Method C is the one to use** if chunking is needed: about 10 % slower than one pass, no second lossy encode, no audio seam. The split point is chosen so that each chunk's length is a whole number of frames. That means it lands at `ceil((body + cd_len/2 − D)·fps)/fps − body + D` into the countdown. [found 2026-09-26]
- Chunk boundaries must fall at a countdown (the chunk must start with a countdown's second half). Detecting a long list is then simply "more than K songs → split every K songs". [found]
- Audio-only never needs chunking: its single pass takes about 1 s per song. [found]

**Open flags for the maintainer** (not decided here, per CLAUDE.md):
1. **"End time past song length" row error** is now caught at manifest stage via metadata (§9), but it adds 0.4–2.7 s of network per row at validation time. The rounding means a second check after download is still needed. That second check is a new failure point at download/render stage that SPEC §8/§9 doesn't have. Is it a row error (skip the song) or a clamp with a warning when the overrun is under ~1 s?
2. **Download format/quality config** (SPEC §7 TODO): 720p cap + H.264 preference works (§9).
3. **JS runtime:** Node works and silences the deprecation warning. Deno is still yt-dlp's default and wasn't tested. Should `setup_once` require Node, Deno, or neither?
4. **Per-row "Mirrored แล้ว" sheet column** exists, but the spec has only the global `processing.mirror`.

## 11. Findings log

Newest first. Date · what was tried · result · where it's now documented.

| Date | Finding | Result | Documented in |
| ---- | ------- | ------ | ------------- |
| 2026-09-26 | moviepy prototype vs this pipeline, same 5 songs | 605 s vs 104 s; prototype output 360p with audio 25 s short | §10 |
| 2026-09-26 | Chunk + join: re-encode / copy-concat / hybrid | hybrid exact and ~10 % over one pass; copy-concat has 9–19 ms audio dropouts | §10 |
| 2026-09-26 | ±1 s padding with clamp | exact lengths, clamps at file start/end | §10 |
| 2026-09-26 | MP4s unplayable on operator PC | `xfade` → yuv444p; fixed with output `-pix_fmt yuv420p` | §10 |
| 2026-09-26 | 720p cap with H.264 sort | both sheet songs 720p H.264 (one at 60 fps) | §9 |
| 2026-09-26 | Node as yt-dlp JS runtime | works, no warning; Deno untested | §9 |
| 2026-09-26 | Length check via metadata before download | works; `duration` rounded to whole seconds → keep ffprobe check | §9 |
| 2026-09-26 | Scratch parser adjusted to new sheet | indices 2/3, whitespace inside timestamps stripped → 2/2 rows | `scratch/test_parser.py` |
| 2026-09-26 | 10-song render baseline, AV1 vs H.264 source | audio 12 s; video 288 s → 118 s with H.264 | §10 |
| 2026-09-26 | `end_time` past file length | FFmpeg exits 0 with corrupt output; must probe first | §10 |
| 2026-09-26 | Long graphs on Windows | ~50-song cmd-line limit; `-/filter_complex file` works | §3 |
| 2026-09-26 | One-pass trim+mirror+crossfade+countdown, audio and video | works, exact durations, needs normalize + known durations | §10 |
| 2026-09-26 | Full download vs `--download-sections` (± keyframes) | full+trim fastest and exact; sections start ~7 s early; keyframes 88 s | §9 |
| 2026-09-26 | yt-dlp without JS runtime | works, same formats, deprecation warning; Node ignored by default | §9 |
| 2026-09-26 | New sheet vs prototype parser | column indices shifted → 0 rows parsed (fixed, see row above) | §4 |
| 2026-09-26 | `static_ffmpeg==3.0` first use | 43 s, 198 MB in venv, FFmpeg 8.0.1, PATH untouched | §3 |