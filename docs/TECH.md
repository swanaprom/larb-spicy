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
- Supported range is read from one file by both scripts: `python-range.txt` at the repo root (e.g. `3.11-3.13`). See §17.
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
- `run`: static → system → else stop with "run setup_once again". No downloading or prompting in `run`. (Until slice 4 the program's lookup did download static-ffmpeg when missing; fixed, §17.)
- FFmpeg (static or system) must be **≥ 7.1**: the renderer needs `-/filter_complex <file>` (7.1+); `xfade` alone would only need 4.3. Older = refused with a clear "too old" message (maintainer decision 2026-09-27, see §12). [found]
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

- A non-public sheet: tested 2026-09-27, the CSV export URL returned **HTTP 401**, which the adapter reports as `The sheet can't be read (HTTP 401). Is it shared as 'Anyone with the link'?` and the run aborts. [found] Older reports say Google may instead answer with an **HTML sign-in page and a success status**, so the adapter also checks that the response really is CSV (content type, body not starting with `<`). Keep both checks. [known, not reproduced]
- Header mismatch: tested 2026-09-27 with a sheet whose artist column is `ชื่อศิลปิน` instead of `ศิลปิน`. The run aborts before any download, naming the missing header and listing the headers found. [found]
- Special-character / encoding handling already solved in the prototype script — port it over **with a comment explaining why it exists**, so nobody deletes it as unnecessary. [found — prototype]
- Local CSV file path is the fallback input (SPEC §9 stage 2).
- Current sheet layout (2026-09): `ชื่อเพลง, ศิลปิน, URLs, ช่วงเวลา, ผู้เสนอเพลง + ชั้นปี, Mirrored แล้ว, หมายเหตุ` → URL index 2, time range index 3. People type stray spaces inside numbers (`1. 04`, `0.4 6-1:3 0`), so strip **all** whitespace before parsing a time range. The moviepy-era CSV used `HH:MM:SS` in separate start/end columns instead. [found 2026-09-26]

## 5. Config (TOML)

- Read: `tomllib` (stdlib, 3.11+). Write: `tomli-w` (pinned). [known]
- Written once per run (at Run), after whole-config validation. Atomic write: write to a temp file **in the same directory**, then `os.replace()` onto `config.toml`. [known]
- TOML writers drop comments and may reorder keys → comments live only in `config/example.toml`. [known]
- Unsaved edits on GUI close: save or prompt (see SPEC §7).
- Tested 2026-09-27 with `tomli-w 1.2.0` (installed in the venv; **not yet added to `requirements.txt`**, since pins need the maintainer). Script: `scratch/spike_toml.py`. All results [found]:
  - Defaults for exactly the SPEC §7 keys generate on first run and read back identically. Round trip is exact for Thai text, Windows backslash paths (written escaped, e.g. `"D:\\งานเต้น\\…"`), `[]()&`, URL queries, and floats like `0.1`. Table and key order are kept (dict order).
  - Comments are dropped on write (as expected).
  - `None` is not a TOML value. `tomli_w.dumps` raises `TypeError` **before** the disk is touched. Empty string / empty list are fine, so use those for "unset".
  - A hand-edited broken file gives `TOMLDecodeError: Invalid value (at line 2, column 10)`. Wrap it in a project error and show the position to the operator.
  - Atomic write (`mkstemp` in the same dir → write → `fsync` → `os.replace`): a simulated crash before the replace leaves the old file intact and no `.tmp` behind.
  - ⚠ **Windows: `os.replace` fails with `PermissionError: [WinError 5] Access is denied` while another handle has `config.toml` open** (another program, antivirus, sync client). Fix: retry a few times with a short sleep (tested: it succeeded once the other handle closed), and never keep the config file open in our own code (`with open(...)` only).
  - ⚠ **`tomllib` rejects a UTF-8 BOM** (`Invalid statement (at line 1, column 1)`), which Notepad writes when saved as "UTF-8 with BOM". Fix: `tomllib.loads(path.read_text(encoding="utf-8-sig"))`. That reads BOM and non-BOM files the same; CRLF line endings are fine.
  - Missing or unknown keys can be found by comparing against the defaults dict. That's the basis for "fill in missing keys with defaults" on load.

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
- The same `info` dict can be handed to `ydl.process_ie_result(info, download=True)`, so each video's metadata is fetched only once. [found] ⚠ **Only on the same `YoutubeDL` instance, or with raw info** (`process=False`): processed info reused by a different instance got 403 on every audio download (slice 2, §14).
- ⚠ **`duration` is whole seconds, rounded** (metadata 217 vs real file 216.828 s; 162 vs 162.191). An end time within about 0.5 s of the end can pass the metadata check and still overrun the real file. **The early check doesn't replace the ffprobe check after download**; it only catches most bad rows early. [found]
- **Prefer H.264 sources:** YouTube's default 720p pick was AV1, and software AV1 decoding made the render **2.4× slower** (§10). [found]
- Always pass `--ffmpeg-location <static bin dir>`: otherwise yt-dlp merges with whatever `ffmpeg` is on PATH (a system FFmpeg exists on this PC). [found]
- Pass `--no-playlist`: sheet URLs contain `&list=RDMM…`. [found]
**Parallel downloads: 1 vs 2 vs 5 at once** — `scratch/spike_parallel.py`, measured 2026-09-27. The same 5 songs as the moviepy comparison, a fresh empty folder per run, no JS runtime. Home connection, i5-6400.

| Mode | Workers | Runs (wall time) | Typical | vs one at a time |
| --- | --- | --- | --- | --- |
| Video 720p (173 MB) | 1 | 72.2, 74.6, 66.8 s | ~71 s | — |
| Video 720p | 2 | 53.4, 57.9, 58.0, 52.1 s (complete runs) | ~55 s | **~1.3× faster** |
| Video 720p | 5 | 49.7, 51.7 s | ~51 s | **~1.4× faster** |
| Audio only (18 MB) | 1 / 2 / 5 | 16.4 / 11.2 / 7.6 s | — | 1.5× / **2.2×** |

- **Video is bandwidth-bound.** Throughput tops out around 3.3–3.5 MB/s with 2 or more workers (2.3–2.6 MB/s with one). Going from 2 to 5 workers adds little, because each song just gets a smaller share: with 5 workers each song takes 26–52 s instead of 10–20 s. [found]
- **Audio is latency-bound** (small files; the per-song metadata round trip dominates), so more workers keep helping. [found]
- ⚠ **Intermittent `HTTP Error 403: Forbidden`:** 2 of 70 video downloads, both in 2-worker runs, each a different song, each failing fast (~2 s). There were none in the 1-worker runs (15 downloads), the 5-worker runs (10) or the audio runs (15). With so few failures, this **can't be pinned on parallelism**. It matches YouTube's occasional 403 on format URLs, possibly related to running without a JS runtime ("some formats may be missing"). Per the maintainer's decision, no JS runtime was tried. [found]
  - Mitigation to build: retry a failed song (fresh metadata extraction) 1–2 times before making it a row error. A retry wrapper was written but **never exercised**: the 3 runs with retry enabled had no 403. [verify]
- Suggested default: **2 parallel downloads**. That gets most of the video gain, with less strain on YouTube than 5. Nothing else is decided here: the worker count is not in the SPEC §7 schema, so it's either hard-coded or a maintainer schema change. [found → maintainer]
- For comparison, the moviepy prototype also used 5 workers.

**Parallel downloads matrix: 1–5 at once, 12 songs** — `scratch/spike_parallel_matrix.py`, 2026-09-27. Replaces the 5-song estimate above. Rows 1–12 of `workspace/moviepy_table/entry.csv`; 12 divides evenly by 1–4, so there's no lopsided last round. Runs were interleaved 1→5 per round (video 2 rounds, audio 3), each from an empty folder, with one retry per failed song. No JS runtime; Node was off PATH. Raw results: `workspace/spike/par/matrix.csv`.

"Avg s per song" = total time ÷ 12, the effective cost of each song.

| Mode | Workers | Avg s per song (runs) | Speed | vs one at a time | 403 on first try | Failed after retry |
| --- | --- | --- | --- | --- | --- | --- |
| Video 720p (390 MB) | 1 | **15.4** (17.8, 12.9) | 2.17 MB/s | — | 0 / 24 | 0 |
| | 2 | **10.0** (10.4, 9.6) | 3.27 MB/s | **1.54×** | 5 / 24 | 0 |
| | 3 | **10.0** (11.0, 9.0) | 3.29 MB/s | **1.54×** | 3 / 24 | 0 |
| | 4 | 11.2 (12.6, 9.7) | 2.96 MB/s | 1.38× | 2 / 24 | 0 |
| | 5 | 11.4 (11.9, 10.8) | 2.87 MB/s | 1.35× | 2 / 24 | 0 |
| Audio (41 MB) | 1 | **3.66** (3.53, 3.89, 3.56) | 0.93 MB/s | — | 5 / 36 | 0 |
| | 2 | 1.89 (1.89, 1.85, 1.92) | 1.79 MB/s | 1.94× | 0 / 36 | 0 |
| | 3 | 1.83 (1.56, 1.89, 2.04) | 1.82 MB/s | 2.00× | 2 / 36 | **1** |
| | 4 | 1.65 (1.56, 1.49, 1.90) | 2.08 MB/s | 2.22× | 1 / 36 | 0 |
| | 5 | **1.49** (1.43, 1.36, 1.68) | 2.29 MB/s | **2.46×** | 0 / 36 | 0 |

- **Video: 2–3 at once is the sweet spot** (~10 s/song, 1.54×). 4–5 is *slower* than 2–3: the connection is already full, and more downloads at once only add overhead. [found]
- **Audio keeps improving up to 5** (2.46×), with smaller gains after 2 (1.94×). The files are small, so per-song lookup time dominates. [found]
- **Network variance is large.** The same setting differed by up to 38 % between rounds (video, 1 worker: 17.8 vs 12.9 s/song). Treat differences under ~10 % as noise; for example, 2 vs 3 workers is a tie. [found]
- ⚠ **403 is not caused by parallelism.** First-try `HTTP Error 403: Forbidden`: 20 of 300 downloads (video 12/120 = 10 %, audio 8/180 = 4.4 %). The one-at-a-time audio runs had 5 of 36, and there's no rising trend with more workers. It's YouTube's intermittent 403 (all 13 affected runs show the same message), likely tied to running without a JS runtime. [found]
- **One retry fixes almost all of them:** 19 of 20 recovered, and 1 song of 300 (0.3 %) failed its retry too. So retry **2** times before making it a row error. The retry is now exercised [found], replacing the earlier "[verify]".
- Suggested default (not decided here): 2–3 at once for video, and up to 5 for audio. The worker count and retry count aren't in the SPEC §7 schema → maintainer: hard-code or add config.

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
| End-to-end wall time | **605 s** | **104 s** (download 49 s with 5 parallel workers + video 50 s + mp3 5 s) |
| Video | 640×360 25 fps | 1280×720 30 fps |
| Video / audio length | 202.68 s / **177.71 s** ✗ | 202.70 s / 202.70 s |

- About **5.8× faster** end to end, at a higher resolution. The prototype log has no timestamps, so its download/render split is unknown. Its `format: "mp4"` pulls a slow fragmented stream (visible as `.part-FragN` files). [found 2026-09-26]
- Prototype defects seen (for the record, not to fix): the output size is taken from the first clip (the 640×360 countdown), so 720p songs are cropped or downscaled; the final audio is 25 s shorter than the video, and per the operator's listening check it contains **only the countdown audio, none of the songs**. It did get one thing right: the countdown volume is normalized (`AudioNormalize`). [found; audio content confirmed by operator 2026-09-27]
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

- In method C, `hvideo_N.mp4` has **no audio on purpose**. It's the intermediate copy-joined video (`-map 0:v`) before the one-pass audio is muxed in to make `hybrid_N.mp4`. [known]

**Audio normalization** — `scratch/spike_loudness.py`. 4 songs + 4 countdowns; the loudnorm modes used target `I=-14 LUFS, TP=-1.5 dBTP, LRA=11`. Scored by the measured loudness of each segment's middle in the output:

| Mode | Songs (LUFS) | Countdown (LUFS) | Spread | Extra time |
| --- | --- | --- | --- | --- |
| none | −5.4 … −10.9 | −28.1 | 22.7 LU | — |
| **peak to −1 dBFS (= moviepy `AudioNormalize`) — CHOSEN** | **−6.4 … −11.9** | **−14.1** | **7.7 LU** | **~0.5 s measuring per clip** |
| `loudnorm` single pass (dynamic) | −13.2 … −16.3 | −13.8 | 3.1 LU | +3 s render |
| `loudnorm` two-pass, `linear=true` | −14.2 … −14.8 | −15.0 | 0.8 LU | ~1.2 s measuring per clip |

- **Chosen: peak normalization** (operator listening check, 2026-09-27). It sounded best: the music isn't pulled down, so the countdown doesn't pop out over it. The lowest LUFS spread isn't the goal here: evening out loudness makes the quiet countdown as loud as the songs, and that stands out. **Hard-coded feature, no config key** (maintainer decision). [found]
- Peak recipe: pass 1 runs `volumedetect` on each clip's exact trimmed (padded) range and reads `max_volume: X dB`. Gain = `−1.0 − X` dB. In that segment's chain, `volume=<gain>dB` goes before `aresample`. Songs near full scale move by ~1 dB; the countdown got about +14 dB. `scratch/spike_loudness.py` mode `peak`. [found]
- Peak caveats: `volumedetect` reports **sample** peak rounded to 0.1 dB, not true peak. With 1 dB of headroom, small inter-sample overs after lossy encoding are possible but weren't heard. A clip with one loud transient gets little boost, which is the nature of peak normalization. [known]
- Alternative tried, not chosen — two-pass loudnorm: Pass 1 measures each clip's exact trimmed range (`loudnorm=…:print_format=json -f null -`). Pass 2 is `loudnorm=…:measured_I=…:measured_TP=…:measured_LRA=…:measured_thresh=…:offset=…:linear=true`, placed in each segment's chain inside the one-pass graph, **before** `aresample=48000`, because loudnorm outputs 192 kHz. [found 2026-09-27]
- Confirmed it really stayed linear (`normalization_type: linear`, one fixed gain, no pumping) for the countdown (+13 dB) and the songs. loudnorm quietly falls back to dynamic when a linear gain would break the true-peak limit, so check `normalization_type` from pass 2 and log it. [found]
- The K-pop masters measured −5 to −8 LUFS with true peaks **above 0 dBTP** (+1.32, +0.37). The countdown is −27 LUFS. At −14 they're turned down 6–9 dB; a louder target means the countdown needs more boost and hits the true-peak limit sooner. [found]
- Measuring can reuse the cache: a clip's measurement depends only on (file, start, end), so it can be cached next to the media. [known]
- Listening files: `workspace/spike/norm/norm_{none,peak,dyn,twopass}.mp3`. Operator verdict: **peak** best. [found 2026-09-27]

**Maintainer decisions received 2026-09-27** (to be written into SPEC by the maintainer):
- End time past song length **after download, within ~1 s**: **trim to fit, with a warning** (not a row error). Larger overruns are still caught at manifest stage by the metadata check (§9).
- **JS runtime: not required.** Don't install or require Deno/Node unless yt-dlp actually breaks without one. Note: the tests in this spike ran with Node on PATH; the operator has since removed it from PATH.
- Speed target: the numbers above are enough.
- **Audio normalization: peak to −1 dBFS per clip, always on, hard-coded (not in the TOML schema).**

**Open flags for the maintainer** (not decided here, per CLAUDE.md):
1. **SPEC clarification needed — mirror.** The operator's intent has two modes: (a) **mirror everything**: rows marked already-mirrored in the sheet's "Mirrored แล้ว" column are left as they are, all others get `hflip`; (b) **leave as is**: nothing is flipped, whatever the column says. The current SPEC has only `processing.mirror = true/false` and doesn't mention the column, so it reads as "flip everything" or "flip nothing".
2. **Download format/quality config** (SPEC §7 TODO): 720p cap + H.264 preference works (§9).
3. **`tomli-w` pin:** 1.2.0 was installed for the test; `requirements.txt` is still empty.

## 11. Findings log

Newest first. Date · what was tried · result · where it's now documented.

| Date | Finding | Result | Documented in |
| ---- | ------- | ------ | ------------- |
| 2026-10-01 | Est. Length live, 3-song sheet, audio + video, uncached and cached | estimate = the run's plan to 0.01 s in every case; countdown downloaded by the estimate, found cached by the run | §21 |
| 2026-10-01 | Est. Length on the 96-row Big Sheet, then a real audio run | estimate < 2 s, zero YouTube requests; run 3841.195 s = estimate; no bot check in 88 requests | §21 |
| 2026-10-01 | `test_shortcuts` with a Thai keyboard active | 5 errors (no keycode for keysym), also on `main`; an in-process US layout doesn't help | §21 |
| 2026-10-01 | 403 retry waits 0 / 2 / 5 s, 309 audio downloads, 15 min, home connection | 12 first-try 403s (3.9 %), all recovered (11 on retry 1); no bot check; sample too small to rank waits → fallback 2/4/8 s ±25 % | §20 |
| 2026-10-01 | Cache-aware checking, live sheet, audio + video | second identical run: 0 look-ups (23 s → 6 s audio); other mode still looked up | §20 |
| 2026-10-01 | `.mp3` countdown in video mode | black screen + sound, 1 warning; old code failed in FFmpeg | §20 |
| 2026-10-01 | Render progress via `-progress pipe:1` | ms of planned output; real events through `ProgressView`: never empty and still | §20 |
| 2026-10-01 | Venv whose Python was uninstalled: `run.bat`, `setup_once.bat` | both rebuild with an announcement; an interrupted rebuild skipped FFmpeg (fixed) | §20 |
| 2026-09 | Real Ubuntu 24.04 PC (maintainer) | works; tkinter hint needed; Open file needs a media player; a cached countdown still triggered the bot check | §20 |
| 2026-09-30 | Ctrl+C / V with Thai, US, Korean, Japanese layouts (real key messages, test thread only) | Thai did nothing before; all four work by key code; Linux needs its own binding tag | §19 |
| 2026-09-30 | Window icons, taskbar identity, Windows 11 caption colour | small = white 16 px, big = accent 32 px (WM_GETICON); DARK title bar seen on screenshot | §19 |
| 2026-09-29 | Window live: audio, video, private and mismatch sheets, stop while downloading / rendering, close during a run | all as GUI.md; stop ends 1.8 s / 3.3 s after the confirmation | §19 |
| 2026-09-29 | Thai / Korean / Japanese in Tk: Windows 11 and WSL Ubuntu 26.04 | Windows fine; WSL has no fonts (boxes) until fonts-thai-tlwg + fonts-noto-cjk | §19 |
| 2026-09-29 | Screenshots of the window: CopyFromScreen vs PrintWindow | CopyFromScreen can capture whatever covers the window; PrintWindow only the window, Tk loop must keep running | §19 |
| 2026-09-29 | Stopping FFmpeg with "q" on stdin, MP3 and 720p H.264, 3 runs each | exits 0.11–0.17 s / 0.42–0.47 s after the stop; partial files stay readable | §18 |
| 2026-09-29 | Cancelling a real yt-dlp download from its progress hook | `StoppedError` 1.0 s after cancel; only a `.part` left, removed by the core | §18 |
| 2026-09-28 | Video in 12-segment chunks + one-pass audio, 3 / 6 / 71 songs | same frame count as one pass; 6-song chunk 0.83 GB; 3-song render +2.6 % vs slice 2 with the audio pass in parallel (+17.5 % without) | §16 |
| 2026-09-28 | `-threads 1` per input, one-pass video 2 / 4 / 6 songs | ~9 % less memory, same time; not enough on its own | §16 |
| 2026-09-28 | Audio ~6 ms short per segment: cause | Opus container length > decoded audio (countdown 5.341 vs 5.329 s); not the seek. Fixed with `apad` + `atrim` | §16 |
| 2026-09-27 | Audio-only output length vs plan, 3 / 10 / 20 / 71 songs | ~6 ms short **per segment** (Opus sources?); ≥ 10 songs fails the 0.1 s length check → run aborts | §14 |
| 2026-09-27 | Long list (71 songs) in one pass; FFmpeg peak memory at 2 / 4 / 6 / 10 songs | video: ~0.54 GB per song, 10 songs already > 3.9 GB → 71 in one pass impossible on 16 GB; audio: 0.32 GB, 85 s | §14 |
| 2026-09-27 | Slice 1 vs slice 2 end to end, live sheet, alternating | audio 21.3 / 19.6 → 14.0 / 14.2 s; video 96.7 / 75.9 → 79.5 / 68.1 s | §14 |
| 2026-09-27 | Manifest look-ups 1 / 3 / 5 at once, live sheet + 12 videos | 12 videos: 24.1 → 9.4 s (3) → 7.1 s (5) | §14 |
| 2026-09-27 | Reuse looked-up info for the download | ~1.5 s saved per song; only raw (`process=False`) info works, processed info → 403 | §14 |
| 2026-09-27 | End fade-out curve: linear → quadratic (`qua`) | last 50 ms −30 dB → −58 dB on the live output | §13 |
| 2026-09-27 | Slice 1 live runs: countdown URL, `--rows`, end fade-out, log file | all work; linear fade still ~−30 dB in the last 50 ms, last frame luma ~20 | §13 |
| 2026-09-27 | Plain `python -m unittest` from the repo root | ran **0 tests** (no `tests/__init__.py`); fixed | §13 |
| 2026-09-27 | Private sheet and header-mismatch sheet, live | private → HTTP 401 (not an HTML page); both abort before download with clear messages | §4 |
| 2026-09-27 | FFmpeg minimum raised to 7.1; settings file moved to `config/config.toml` | old FFmpeg refused with clear message (offline test); live run reads new path | §3, §12 |
| 2026-09-27 | Walking skeleton on live sheet (3 songs), audio + video | length checks pass; mirror rule confirmed from frames; cached re-run downloads nothing; real 403 fixed by retry | §12 |
| 2026-09-27 | yt-dlp prints errors despite `quiet` | silent `logger` option | §12 |
| 2026-09-27 | Parallel matrix 1–5 workers, 12 songs, 300 downloads | video best at 2–3 (1.54×), 4–5 slower; audio 2.46× at 5; 403 on 20/300 first tries, not tied to parallelism; 1 retry fixes 19/20 | §9 |
| 2026-09-27 | Parallel downloads 1 / 2 / 5 workers, 5 songs | video ~1.3× (2) / ~1.4× (5), bandwidth-bound; audio 2.2× at 5; 2 intermittent 403s of 70, cause unclear | §9 |
| 2026-09-27 | TOML generate/read/write with tomli-w 1.2.0 | round trip exact; Windows `os.replace` fails on open file → retry; BOM rejected → `utf-8-sig` | §5 |
| 2026-09-27 | Audio normalization, 4 modes + listening check | **peak chosen by ear** (hard-coded); two-pass loudnorm measured most even (0.8 LU) but pops the countdown out | §10 |
| 2026-09-27 | `hvideo_6.mp4` silent | intended (intermediate video-only file of the hybrid join) | §10 |
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
## 12. Walking skeleton (2026-09-27, branch `skeleton`)

**Layout.** `src/larb/core/` (models, ports, errors, manifest rules, cache naming, settings validation, pipeline; standard library only) · `src/larb/adapters/` (`toml_settings`, `sheet_csv`, `ytdlp_media`, `ffmpeg/{helper,locate,processor}`, `console_events`) · `src/larb/cli.py` (the only place that wires adapters to ports) · `tests/test_smoke.py`.

**Run it** (repo root, existing venv; no setup scripts yet):
```
set PYTHONPATH=src
.venv\Scripts\python.exe -m larb "<sheet URL or CSV path>" --countdown "tests/fixtures/countdown/!countdown.mp4" [--verbose]
.venv\Scripts\python.exe -m unittest discover -s tests -v      # offline smoke test
```
`--verbose` also prints every FFmpeg/ffprobe command, pasteable into a terminal.

**Measured on the live sheet (3 songs, i5-6400).** All runs [found 2026-09-27]:

| Run | Manifest (3 YouTube look-ups) | Downloads | Render | Total |
| --- | --- | --- | --- | --- |
| Audio, first run | 7 s | 8 s (one real 403, fixed by 1 retry) | 3.3 s | 20 s |
| Video 720p + mirror, first run | 7 s | 44 s | 31 s | 83 s |
| Video again (all cached) | 7 s | 0 | 35 s | 42 s |

- Output length check passed every time (audio 138.99 s = planned; video 139.03 s vs 139.02 s planned). The video is H.264 `High`, `yuv420p`, 1280×720, 30 fps.
- Mirror rule checked visually from frames: Perfect Night flipped; Drama (marked) not flipped; Ditto (cell is only spaces) flipped.
- Cache: `<id>_audio.webm` and `<id>_v720.mp4` side by side; a second run with the same settings downloads nothing.

**Implementation notes** [found unless marked]:
- **The settings file is `config/config.toml`** (gitignored), **not** inside `workspace/`. `workspace/` gets deleted to free space, and settings must survive that (maintainer decision 2026-09-27). On first run it's created by copying `config/example.toml` **as text**, so it keeps the explanatory comments. Keys missing from an older file are filled from the template on load.
- **Minimum FFmpeg is 7.1** (maintainer decision 2026-09-27, replacing SPEC's ≥ 4.3). The renderer passes the filter graph as a file with `-/filter_complex <file>`, which exists from 7.1. The older `-filter_complex_script` fallback was removed rather than kept untested. An older FFmpeg, static or system, is refused with `No usable FFmpeg: version 7.1 or newer is needed … system FFmpeg 4.4.2 (…) is too old` (checked offline in `tests/test_locate.py`). Version strings without a number (dev builds like `N-12345-g…`) are accepted; if one ever lacks the option, FFmpeg itself fails and the run stops with a `RenderError`. [found]
- **yt-dlp prints its own `ERROR:` line on stderr even with `quiet=True`.** A do-nothing `logger` object in the options silences it; the core logs our own message instead.
- **Audio-only downloads (`ba/b`) arrive as `.webm` (Opus).** That's fine: the cache keeps the file's own extension (HANDOFF rule).
- **Each song's metadata is fetched twice** (`lookup` at manifest stage, then again inside `download`), about 1.5–3 s extra per song. The early YouTube check stays (maintainer decision). → **Done in slice 2** (§14): fetched once, ~1.5 s saved per song.
- **Manifest look-ups run one at a time** (0.5–3 s per row): roughly 5–10 min for ~300 rows before downloads start. → **Done in slice 2** (§14): parallel, ~2.6× faster at the default 3.
- The clipped K-pop masters measure a sample peak of exactly 0.0 dB, so peak normalization gives them −1.0 dB. The countdowns get +14 dB.
- Output is rendered to `<name>.rendering.<ext>` and renamed only on success; a failed render leaves no file under the final name. The graph file is kept in `workspace/tmp/` when a render fails, for debugging. ⚠ This held only for a failed FFmpeg run: an output rejected by the length check kept its final name (§14). Fixed in slice 3 (§16): the core now does the naming, after the check.
- Output length is verified through `MediaProcessor.measure(output, 0, 0.1)`. The tiny range keeps the peak scan cheap, since only the file length is needed. A dedicated "length" method would need a port change. [known]
- `static-ffmpeg 3.0` declares `twine`, `requests`, `filelock` and `progress` as runtime dependencies. `twine` looks like an upstream packaging slip, but it's pinned anyway, as instructed.

**Maintainer decisions received 2026-09-27** (on behavior first chosen in code; to be written into SPEC / CLAUDE.md by the maintainer):
1. **Output and cache folders chosen by the operator** may be outside `workspace/`; the defaults stay in `workspace/`. (CLAUDE.md's "never write outside workspace/" is about test runs, not about overruling the operator.)
2. **Time-range format**, approved; a row error for ambiguous input is the right call:
   - Seconds must have **two digits** (`1.5` is a row error rather than guessed as 1:05 or 1:50).
   - `h:mm:ss` is accepted.
   - The `–` / `—` dashes phones insert are accepted.
   - Seconds of 60 or more are a row error.
3. **Settings ranges**, approved: `crossfade_duration_seconds` > 0 and ≤ 10 (no "no crossfade" option needed); `max_height` 144–4320 and even; `max_parallel_downloads` ≥ 1; `max_retries` ≥ 0.
4. **Silent clip** (peak ≤ −60 dB): no gain plus a warning, approved.
5. **`filename_template`**: only `{date}` and `{time}`; characters illegal in Windows file names are refused. Approved.
6. **FFmpeg minimum 7.1** and the settings file at `config/config.toml`: see the notes above.

Playback: all skeleton outputs play in Windows' built-in player (checked by the maintainer, 2026-09-27).

## 13. Slice 1 — polish (2026-09-27, branch `slice-1-polish`)

**Run it** (repo root, venv):
```
set PYTHONPATH=src
.venv\Scripts\python.exe -m larb "<sheet URL or CSV>" [--countdown FILE_OR_URL] [--rows 2-10] [--verbose]
.venv\Scripts\python.exe -m unittest -v
```

**Countdown from a URL.** `--countdown` is a URL when it starts with `http://` or `https://`, otherwise a file. Without it: `countdown.default_urls[0]`, then `default_files[0]` (`core.pipeline.choose_countdown`). A URL goes through `MediaSource.lookup` + `download` like a song: same cache name (`qW9N8XjUkIE_audio.webm`, `qW9N8XjUkIE_v720.mp4`), same retries, same peak normalization (the live countdown gets +14.2 dB). Unavailable, or still failing after retries → the run aborts. [found]
- **Order changed (maintainer decision 2026-09-27):** the countdown is prepared **after** the sheet is read and **before** the manifest, so a bad countdown stops the run before minutes of YouTube look-ups. The sheet still comes first, so a bad sheet still aborts before any download. This differs from the SPEC §9 stage order.
- A cached countdown still costs one `lookup` (~2 s), because the cache name needs the video ID. Same as songs.
- ⚠ **`default_urls` must be quoted in TOML:** `default_urls = [https://…]` fails with `Invalid value (at line 6, column 17)`; it must be `["https://…"]`. Seen in a hand-edited `config.toml`. The run stops with that message, which is correct but not very friendly. [found]

**End fade-out.** `RenderPlan.fade_out_s` (port change approved 2026-09-27): the core sets it to the crossfade duration, the FFmpeg adapter adds `afade=t=out:st=L−f:d=f:curve=qua` and `fade=t=out:st=L−f:d=f:color=black` after the last join, where `L` is the planned length. The fades only scale samples/pixels, so the length is unchanged (live: 138.99 s vs 139.02 s planned, same as before). [found]
- **Audio curve: `qua` (quadratic), maintainer choice 2026-09-27.** The first version used `afade`'s default linear curve (`tri`): on the live output that was −7 dB over the last 0.5 s and still about **−30 dB in the last 50 ms**, just audible. With `curve=qua` (gain = square of the time left) the same live output measures −1.5 dB at 1.0–0.5 s before the end, −13.5 dB over the last 0.5 s, **−57.8 dB in the last 50 ms**, −91 dB (digital silence) in the last 20 ms. Length unchanged (138.99 s). [found]
- The offline test checks the last 20 ms against −30 dB (fixtures with `qua`: −91 / −84 dB), plus sound before the fade where the last song is loud to its end (−0.7 / −3.5 dB). [found]
- Video: average luma of the last frame ~**20** (black = 16) vs ~138 without the fade. The last frame starts 1/30 s before the end, so it's not fully black by design; the test threshold is 30. [found]
- The tests were checked against a build with the fade forced to 0: both fade tests then fail (end peak −1.7 / −7.3 dB). [found]
- If the last song is shorter than two crossfades, the fade-out overlaps the join's crossfade. Harmless, just shorter at full volume. [known]

**Row range.** `--rows 2-3`, `--rows 5` (= 5-5); any dash, spaces ignored. Checked in two steps: the form (backwards, header row 1, not a range) before anything runs; the extent after the sheet is read ("outside the sheet: the last song is on row 4"). The last row is the last row **with content**, because the sheet adapter drops fully empty rows; row numbers still match the sheet. Rows outside the range are never looked up. [found]

**Log file.** `workspace/logs/<date>_<time>.log` (`_2`, `_3` … for runs in the same second). Named by the run's start time, not the output's name (maintainer: fine). Always includes DEBUG (the exact FFmpeg commands), whatever the console shows (maintainer decision). At start, older logs are deleted so the folder never holds more than 5 files, the current run's included. "Newest" is judged by the date/time in the name, not the modified time. Only files named like a log are ever deleted. [found: 7 live runs → 5 logs]

**Cache-clear prompt.** After a successful run, only when both stdin and stdout are a terminal. Enter, anything but `y`/`yes`, Ctrl+C, or closed input = No. Clearing deletes only files named by the cache rule (`<id>_audio.*`, `<id>_v<n>.*`, including leftovers like `.part`, `.f136.mp4`, `.ytdl`), never subfolders or other files, because the operator may point the cache at a shared folder. Limitation: a file the operator named like `my_audio.mp3` matches the rule. [known]
- Checked by the maintainer in a real terminal, 2026-09-27: works as intended. Claude's shell isn't a terminal, so it's (correctly) never asked there. [found]

**Tests.** `python -m unittest` from the repo root ran **0 tests** before: `tests/` had no `__init__.py`, and discovery only enters packages. Added it; `discover -s tests` still works. Shared fakes live in `tests/fakes.py` (not `test_*.py`, so it isn't collected twice). 26 tests, ~18 s.

## 14. Slice 2 — speed (2026-09-27, branch `slice-2-speed`)

Scripts for the measurements below were throwaway (not committed); inputs are in `workspace/slice2/`: `list12.csv` (the spike matrix's 12 songs, `0:30-1:05` each, in the live sheet's columns) and `long.csv` (the same 12 × 6 different 35 s ranges = 72 rows; row 69 runs past its song, so 71 usable). `workspace/slice2/long_cache/` holds their 720p videos, so the long-list test can be rerun without downloading. i5-6400, home connection, yt-dlp 2026.08.19, no JS runtime.

**Port changes (approved by the maintainer 2026-09-27):** `MediaUnavailableError.retryable` (default False), so look-ups follow the download retry policy; `LogEvent.progress = (done, total)` (default None), so the GUI reads progress from a field, never from message text.

**Look each video up once.** `lookup` remembers the info; `download` reuses it once (then forgets it), in a fresh `YoutubeDL` with the download's own format options, via `process_ie_result(info, download=True)`. Nothing leaves the adapter; the core and the port didn't change for this.
- ⚠ **Only raw info can be reused.** First try: `extract_info(url, download=False)` (processed: yt-dlp has already picked a format) reused in another `YoutubeDL` → video worked once, but **every audio download got `HTTP Error 403`** (8 of 8, 4 songs × 2 rounds), while fresh downloads of the same songs all worked. Not cookies: copying the look-up's cookie jar into the download's instance still gave 403. What works: the same instance for both (not possible: the port's `lookup` doesn't know the media kind), or **`extract_info(..., process=False)`** (raw info, no format picked) handed to the download's instance. [found]
- ⚠ With `process=False`, a sheet URL carrying `&list=RDMM…` returns `{"_type": "url", ...}`, a redirect to the video itself, with no length. The adapter follows it (≤ 3 hops) before reading `duration`; otherwise the length check fails and the download would silently look the video up again. `youtu.be/…?si=`, `music.youtube.com` and `/shorts/` give the video directly. Unavailable and truncated IDs fail as before. [found]
- Reused info picks the same formats as a fresh look-up: video `136+140` (720p H.264 + AAC), audio `251`. [found]
- Size: raw info is ~0.5 MB per video, ~80 % of it `automatic_captions`. Captions, subtitles and heatmap are dropped before remembering → ~70 KB, ~20 MB for 300 rows. [found]
- **Fallback to a fresh look-up** (logged at INFO: `... looking it up again`): no remembered info (e.g. the core's own retry, since info is used only once), info older than 1 hour (`REMEMBER_FOR_S`; YouTube's links expire after ~6 h), or a retryable failure with the reused info. In the live runs this happened for 2 of ~20 downloads, both `HTTP Error 403` in video mode, both fixed by the fresh look-up without using one of the core's retries. That's the usual intermittent 403 (§9), not something reuse causes: 12 of 12 reused audio downloads worked in the timing test below. [found]
- **Time saved:** audio downloads of the 12 songs, alternating reused vs fresh (slice 1 behaviour): reused **1.65 s**, fresh **3.17 s** mean → **~1.5 s saved per song** (median 1.44 s). One fresh download hit the intermittent 403 (excluded). [found]
- Live log (DEBUG, in the log file): `looked up <id> in 2.1 s` once per song, then `downloading <id> with the looked-up info`. [found]

**Parallel look-ups.** `download.max_parallel_lookups` workers (file-only, default 5; see below), retries as for downloads (`max_retries`, pause 1 s × attempt); the countdown's look-up is retried too. Each row's messages are collected in its worker and reported through `pool.map`, which returns in sheet order however rows finish; offline row errors are checked in the workers as well, so every row gets one progress event. Manifest stage only (`Pipeline._build_manifest` with the real adapters), 3 interleaved rounds each: [found]

| List | 1 at a time | 3 at once (default) | 5 at once |
| --- | --- | --- | --- |
| Live sheet, 3 rows | 5.9 / 5.6 / 5.9 s | 2.3 / 2.2 / 2.3 s (**2.5×**) | 2.4 / 2.3 / 2.6 s |
| 12 different videos | 24.4 / 23.5 / 24.4 s | 9.5 / 9.0 / 9.6 s (**2.6×**) | 7.4 / 6.7 / 7.2 s (**3.4×**) |

- Very steady (unlike downloads). A single look-up gets slightly slower with more at once (2.0 → 2.2 → 2.5 s), but the total still drops. With 3 rows, 3 and 5 are the same (all rows at once). 72 rows at 3 at once: 56 s. No look-up needed a retry in any run. [found]
- Look-ups behave like audio downloads (latency-bound), so 5 is faster than 3, while `max_parallel_downloads` = 3 is tuned for video downloads (§9). The first build shared that key; **maintainer decision 2026-09-28: a separate file-only key `download.max_parallel_lookups`, default 5** (schema change approved; SPEC §7 is updated by the maintainer). Must be 1 or more. An older `config.toml` without the key gets 5 from the template on load (checked live: `Checking 3 row(s), up to 5 at once`, `config.toml` left untouched). [found]

**Progress.** A `LogEvent` with `progress=(0, N)` when checking starts, then one `progress=(done, N)` per row as it finishes (console: `row 14: checked 12/40`). Progress events come in finishing order; the row results after them are in sheet order. [found]

**End to end, slice 1 (`main`) vs slice 2**, live sheet (3 songs + URL countdown), each run from its own empty cache, alternated slice 1 → 2 → 1 → 2: [found]

| Mode | slice 1 | slice 2 |
| --- | --- | --- |
| Audio | 21.3 s, 19.6 s | **14.0 s, 14.2 s** |
| Video 720p | 96.7 s (1 retry, slow 52 s render), 75.9 s | **79.5 s, 68.1 s** |

Every run passed the length check (audio 138.99 s vs 139.02 s planned, video 139.17 vs 139.16 s). Manifest stage 4 s → 2–3 s. Video is dominated by download bandwidth and the render, so the ~1.5 s per song saved matters less there.

**Long list in one pass (≥ 60 songs), measured, not built.** No chunking code was written (slice scope). Memory is Windows' `PeakWorkingSetSize` of the FFmpeg render process (earlier try: 2 s sampling). A safety stop killed the run when the system's free memory fell below 1–1.5 GB. The PC has 15.9 GB, but only **2–5 GB was free** during these runs (browser, editor). [found]

| Mode | Songs (inputs) | FFmpeg peak | Render | Result |
| --- | --- | --- | --- | --- |
| Video 720p | 2 (5) | 0.91 GB | 20.5 s | ok, exact length |
| Video 720p | 4 (9) | 2.02 GB | 35.5 s | ok, exact length |
| Video 720p | 6 (13) | 3.08 GB | 49.4 s | ok, exact length |
| Video 720p | 10 (21) | > 3.89 GB | — | **safety stop** (free 1.0 GB) |
| Video 720p | 71 (143) | > 1.92 GB after ~1 min, output still 0 bytes | — | **safety stop** (free 1.0 GB) |
| Audio | 71 (143) | 0.32 GB | 85 s | rendered, but **rejected by the length check** (below) |

- ⚠ **Video: FFmpeg memory grows ~0.54 GB per song** (≈ 0.27 GB per input: 5 → 13 inputs, 0.91 → 3.08 GB), and it keeps rising during the render (6 songs: 1.7 GB at 2 s, 3.1 GB at 45 s), so it's not only a start-up cost. Extrapolated: 10 songs ≈ 5.3 GB, 71 songs ≈ 38 GB. **A one-pass video render of a long list can't work on this PC**, and even 10 songs needs more than ~4 GB free. The spike's 10-song one-pass render (§10) worked, most likely with more memory free. Cause not investigated. Likely: every input is opened and decoded at once, and decoded 720p frames (~1.4 MB each) pile up for inputs the crossfade chain isn't reading yet. Untested ideas: fewer decoder threads per input (`-threads 1` before each `-i`), or chunking (method C, §10), which would also bound memory: at ~0.54 GB per song, ~6 songs per chunk stays near 3 GB. [found → maintainer]
- **Audio in one pass: fast and small** (0.32 GB, 85 s for 71 songs, a 47.8 min output). Audio doesn't need chunking for memory or time (§10). [found]
- ⚠ **Audio-only output is short by ~6 ms per segment**, so the length check (tolerance 0.1 s) rejects any audio run of about 10 songs or more and the run aborts:

  | Songs (segments) | Planned | Actual | Short by | Per segment |
  | --- | --- | --- | --- | --- |
  | 3 (7), live sheet | 139.02 s | 138.99 s | 0.03 s | 4.3 ms |
  | 10 (21) | 404.41 s | 404.29 s | 0.12 s ✗ | 5.7 ms |
  | 20 (41) | 807.82 s | 807.58 s | 0.24 s ✗ | 5.9 ms |
  | 71 (143) | 2865.21 s | 2864.36 s | 0.85 s ✗ | 5.9 ms |

  Video mode (AAC audio from `.mp4`) matches within 0.01 s, and the spike's 10-song audio test was exact (§10). Audio mode downloads Opus (`.webm`, §12). **Suspected cause [verify]: Opus pre-skip / seek pre-roll.** Opus has a 312-sample (6.5 ms) start delay, which input-side `-ss` seeking may drop at every segment. Not fixed here: the render recipe and the audio download format are both outside this slice. Existing behaviour, same in slice 1. [found → maintainer]
- ⚠ When the length check rejects a render, the file stays in the output folder under its **final name** (the rename happens before the check). Only a failed FFmpeg run leaves no file (§12). [found → maintainer]

**Tests.** 46 tests (+20), ~38 s. `tests/test_settings.py`: `max_parallel_lookups` default, an older file without the key, save and read back, minimum 1. `tests/test_manifest_parallel.py`: fake look-ups with delays, so rows finish out of order. It checks that results are in sheet order, each row error is on its row, one progress event per row, permanent errors aren't retried, retryable ones give up after `max_retries`, one at a time really is one at a time, and countdown look-up retries. `tests/test_ytdlp_reuse.py`: yt-dlp replaced by a fake, covering reuse, the `&list=` redirect, info used only once, and the fallbacks (none, expired, failed with 403), plus not repeating a permanent failure and the retryable flag on look-up errors.

## 15. Slice 3 candidates — long-list reliability (proposed; built in slice 3, see §16)

Found in slice 2 (§14), all existing before it. The maintainer moved them to slice 3 (2026-09-28). These are proposals, and the numbers they rely on are in §14. `workspace/slice2/` (`long.csv`, `list12.csv`, `long_cache/` with the 12 videos at 720p) is kept for these tests.

**A. Audio output ~6 ms short per segment** (audio runs of ~10+ songs fail the length check, §14).
1. **Confirm the cause first** (cheap, audio renders take seconds): 20 segments from one song, rendered from the Opus `.webm` and from an AAC `.m4a` of the same video, input-side `-ss` vs no seek. If only Opus + seek loses ~6.5 ms per segment, it's Opus's 312-sample pre-skip / seek pre-roll.
2. **Fix: make each segment exactly its planned length in the render graph**, whatever the decoder does. In each audio segment chain, after `asetpts`: `apad=whole_dur=<D>,atrim=duration=<D>` (pad if short, cut if long). This also protects against any other source that's a few ms off. The planned length (Σ durations − joins × crossfade) then holds by construction, and the length check stays as the guard.
3. **Better, if step 1 confirms the cause:** also get the *content* right, not only the length. Seek a little early and trim exactly in the graph: `-ss <start − 0.5> -t <D + 0.5>` on the input, then `atrim=start=0.5:duration=<D>`. Then no audio is lost at the start (with padding alone, a segment would start ~6 ms late and end with ~6 ms of silence, which can't be heard, but it isn't exact). Keep the `apad` from step 2 as the safety net. Video already matches the plan, so this applies to the audio chains only; it's cheap because audio decoding is fast.
4. Test: the 71-song audio list (`long.csv`) must pass the length check; an offline test with ≥ 20 segments from a small Opus fixture (a few seconds, in `tests/fixtures/`).

**B. A rejected render keeps its final name** (§14): the FFmpeg adapter renames `<name>.rendering.<ext>` → `<name>.<ext>` when FFmpeg succeeds, and only then does the core check the length.
- **Proposal:** the core passes the renderer a temporary path, `<name>.rendering.<ext>` in the output folder, checks its length, and renames it itself: to `<name>.<ext>` if the check passes, to **`<name>_FAILED.<ext>`** if not (never overwriting, same `_2`, `_3` rule as outputs), logging the failed file's path in the ERROR. The adapter's own rename is removed, since it would then be done twice. Same folder, so the rename is atomic and works when the operator's output folder is on another drive (a move from `workspace/tmp/` would be a copy). `render(plan, output_path)` keeps its signature: only what the core passes as `output_path` changes. That's no port change, but the port's docstring should say "renders exactly to output_path".
- A crash mid-render leaves `<name>.rendering.<ext>`. Cleaning up such leftovers at the next run start is optional (they're clearly named).
- Test: a fake processor whose output has the wrong length → no file under the final name, a `_FAILED` file exists, run aborts.

**C. Video: always render in small fixed chunks (hybrid method C, §10); audio stays one pass.**
1. **First, the memory test for `-threads 1`** (per input, before each `-i`; decoder threads, not x264's): 2 / 4 / 6 songs of `long.csv`, with and without it, alternating. Record FFmpeg's `PeakWorkingSetSize` (the measuring method in §14, not sampling), render time and exact length. Also worth one try: `-thread_queue_size` and `-filter_threads`, only if `-threads 1` alone doesn't help. If memory per song drops a lot at a small time cost, it goes in regardless of chunking.
2. **Chunk size from that result**: pick K songs per chunk so the peak stays under ~2 GB (this PC had only 2–5 GB free with a browser open; school PCs may have 8 GB total). With today's ~0.54 GB per song that's K ≈ 3–4. **Fixed K, hard-coded, always**, even for short lists. That gives one code path and one tested recipe, and a 3-song list is simply one chunk. Not a setting (SPEC §7 style); the maintainer decides whether it should be.
3. **Recipe (§10 method C):** video chunks split mid-countdown on a frame boundary (`ceil((body + cd_len/2 − D)·fps)/fps − body + D` into the countdown), each chunk rendered separately, joined with the concat demuxer `-c copy`. The audio for the whole list is rendered in **one pass** (the same audio graph as audio-only mode, with fix A), then muxed with `-c copy`. The measured cost was ~10 % over one pass, with identical frame counts, seams and stream lengths.
4. Checks: each chunk's frame count against its plan, the joined video's length, and the final length check against the plan (as now). With B, a failed chunk leaves a `_FAILED` output and a clear message; chunk files live in `workspace/tmp/` and are deleted after a successful mux. Keeping finished chunks to resume after a crash is possible later, but not proposed now.
5. Test: an offline smoke test with 2 chunks (K forced small, e.g. 1 song per chunk with the tiny fixtures): exact length, A/V lengths equal. Live: the 71-song `long.csv` in video mode must finish, with its time and FFmpeg peak memory reported against the 6-song one-pass numbers (§14).
6. Port impact: none expected. Chunking is inside the FFmpeg adapter's `render(plan, output)`; the core's plan stays one list of segments. If K should be decided by the core (e.g. from settings), that would be a plan/port change and needs approval first.

## 16. Slice 3 — long lists (2026-09-28, branch `slice-3-long-lists`)

i5-6400, 15.9 GB, FFmpeg 8.0.1 (static), 720p. Measurement scripts were throwaway (not committed); inputs are `workspace/slice2/` (§14).

**Port change (approved by the maintainer 2026-09-28):** `RenderPlan.crossfades_s`, one crossfade per join, replaces `crossfade_s`. `render(plan, output_path)` keeps its signature; its docstring now says it renders exactly to `output_path` and may leave a partial file there on failure.

**Countdown default.** `config/example.toml` has `default_urls = ["https://www.youtube.com/watch?v=qW9N8XjUkIE"]`, so a fresh install runs without `--countdown`. `default_files` stays empty (test fixtures are never runtime defaults). Only a **new** `config.toml` gets it: loading fills in *missing* keys, so an existing file with `default_urls = []` stays empty. [found: fresh config, live sheet, no `--countdown` → used the URL, length check ok]

**Audio ~6 ms short per segment — cause confirmed, fixed.** [found]
- Not the seek. 20 × 5 s segments of one song, decoded through the renderer's own audio chain to WAV and counted in samples: exact from the Opus `.webm` and from the AAC track of the same video, with input-side `-ss` and without. A 20-segment render of mid-song segments was exact too (81.000 s).
- **The cause is the countdown, used whole.** An Opus `.webm` reports more in its container than decodes: the YouTube countdown says 5.341 s, and 255 792 samples = 5.329 s decode (the stream starts at −0.007 s, Opus's pre-skip). The plan uses the container length, so every countdown came out 12 ms short. Over the slice 2 lists that is 3 → 0.036 s, 10 → 0.12 s, 20 → 0.24 s, 71 → 0.85 s, matching what was measured there (§14). The AAC countdown (`.mp4`) decodes to its container length, which is why video mode was exact. Songs are unaffected unless their padded end reaches the end of an Opus file.
- **Fix:** every audio segment chain ends with `apad=whole_dur=D,atrim=duration=D` (D = planned length): padded with silence if short, cut if long. The missing 12 ms are at the countdown's end, so the content is not shifted; the "seek 0.5 s early" idea (§15 A3) was for a seek problem that doesn't exist, and was not built.
- A generated tone reproduces it: `sine` 3 s → `libopus` `.webm` reports 3.008 s, decodes 3.000 s. That's the fixture `tests/fixtures/countdown/tone_3s.webm` (recipe in `tests/test_audio_length.py`); 20 songs + 20 of those countdowns failed the length check before the fix (101.00 vs 101.16 s).
- Live: 3-song sheet audio 139.02 s = planned (was 138.99). 71 songs: **2865.21 s = planned** (was 2864.36, rejected), render 99 s, FFmpeg peak 0.32 GB. Slice 2 measured 85 s for the same render; not investigated (the extra `apad`/`atrim` per segment, or noise).
- `measure()` still reports the container length. Reporting the decoded length would need a full decode of every file; the pad/trim makes it unnecessary.

**Output naming: nothing unverified gets the final name.** The core renders to `<name>.rendering.<ext>`, checks the length, then renames it to `<name>.<ext>`, or to `<name>_FAILED.<ext>` (never overwriting: `_FAILED_2` …) when the check fails **or** the render fails after writing anything. A render that fails before writing leaves no file. The FFmpeg adapter no longer renames or deletes anything in the output folder. At run start, leftover `*.rendering.mp3` / `*.rendering.mp4` files in the output folder are deleted (only those two patterns: the operator may point it at a folder with their own files); a file another run still has open can't be deleted on Windows and is skipped with a warning. [found: offline tests]

**Crossfade per join.** Each join's crossfade is the setting, or the longest both clips next to it can hold, whichever is smaller. A clip can hold its length minus one frame (1/30 s), halved when it has a fade on both sides; the end fade-out counts as a fade, so the last clip always has two. So no clip's fades ever overlap, and every clip plays at least one frame on its own, which is where the video chunks are cut. The end fade-out follows the same rule. A song that shortens its joins gets a row warning (`clip is only 3.00 s: crossfades next to it shortened to 1.48 s (setting 2 s)`); the countdown, the same clip every time, warns once per run. Below 3 frames (0.1 s) a countdown stops the run and a song is skipped; this replaces the old "not longer than the crossfade" rules. The default countdown (5.34 s) holds crossfades up to 2.65 s. [found: offline tests, short countdown in audio, short song in video]

**`-threads 1` before each input** (decoder threads), one-pass video, 2 / 4 / 6 songs of `long.csv`, 2 alternating rounds each, `PeakWorkingSetSize` read from the process handle after exit: [found]

| Songs (inputs) | Peak, plain | Peak, `-threads 1` | Render, plain / `-threads 1` |
| --- | --- | --- | --- |
| 2 (4) | 0.87, 0.84 GB | 0.78, 0.78 GB | 19.9, 19.3 / 19.8, 19.2 s |
| 4 (8) | 2.07, 2.04 GB | 1.88, 1.88 GB | 37.1, 36.1 / 39.6, 35.9 s |
| 6 (12) | 3.09, 3.08 GB | 2.81, 2.82 GB | 52.9, 50.7 / 51.4, 50.0 s |

~9 % less memory at the same speed: kept (`DECODER_ARGS`), but memory still grows ~0.5 GB per song in one pass, so it's no substitute for chunking. `-thread_queue_size` / `-filter_threads` were not tried.

**Video: fixed chunks + one-pass audio, joined without re-encoding** (§10 method C), always, in `adapters/ffmpeg/processor.py`: [found]
- The audio of the whole list: one pass, the audio-only graph, AAC (`.m4a` in `workspace/tmp/`). The video: chunks of `CHUNK_SEGMENTS = 12` segments (6 songs), each rendered video-only (`-an` on the inputs). Joined with the concat demuxer and the audio muxed in, both `-c copy`, in one FFmpeg run. Chunk, audio and list files are deleted afterwards, success or not; graph files are kept only for a failed pass.
- **Where to cut:** inside segment 12, 24, … With an even chunk size that is always a countdown (the core puts one before every song), but the adapter doesn't depend on it: the crossfade rule leaves every clip at least one frame of its own. The cut is on a frame boundary: the first one after the middle of the part between the countdown's two crossfades (or the one before, if that part is only ~1 frame). So every chunk but the last is a whole number of frames.
- **Frame-exact chunks.** A first version was a frame short (411 vs 412): `xfade` offsets aren't whole frames, so after a join the frames sit off the 1/30 s grid, and the count depends on rounding. Now each video segment is padded/trimmed to its planned length (`tpad=stop_mode=clone`, `trim`; the countdown's video stream is 5.32 s in a 5.387 s file), the chain ends with `fps=30` and a 1 s cloned tail, and the pass stops at exactly `round(length × 30)` frames (`-frames:v`). Each chunk, and the joined video, are checked against that frame count.
- **Memory of one video-only chunk** (720p, `-threads 1`): 3 songs 0.55 GB, 6 songs 0.83 GB, 10 songs 1.25 GB, 14 songs 1.86 GB; speed ~7.5–8 s per song whatever the size. Much less than the one-pass numbers: those included the audio. **Chosen: 6 songs** (0.83 GB), well under ~2 GB, with room for 60 fps sources or a larger `max_height` (1080p is ~2.25× the pixels), and half the joins of 3-song chunks. The audio pass peaked at 0.06 GB (6 songs).
- **6 songs, chunked (2 chunks) vs one pass:** 7300 frames in both, audio 243.322 s in both. Per-frame PSNR against the one-pass file: 46–62 dB at the cut (frames 3710–3722); lower values (31–45 dB) appear at the ordinary crossfades throughout and in the countdown after the cut (the second chunk starts a new keyframe there), i.e. encoder differences, not a shift or jump.
- **Speed:** audio pass first, then the chunks: 3-song live video render 34.2 s vs 29.1 s on `main` (+17.5 %, render stage, songs cached, alternating 3 runs each). The audio pass needs little CPU or memory, so it now runs **in parallel** with the chunks: **30.3 s vs 29.5 s (+2.6 %)**. Live sheet video: 139.17 s vs 139.16 s planned; streams: video 139.167 s (4175 frames, H.264 High, yuv420p, 1280×720, 30 fps), audio 139.161 s.
- **71 songs (`long.csv`), video:** finished, **2868.48 s = planned**; streams: video 2868.467 s (86 054 frames), audio 2868.478 s. **Render stage 634.8 s** (10.6 min). FFmpeg peaks: 12 video chunks 0.67–0.93 GB (42–58 s each), the audio pass 0.59 GB (351 s, in parallel), join + mux 0.05 GB (5.3 s); **highest 0.93 GB** (one pass: 71 songs would need ~38 GB, §14). Chunk joins at 4:05.03, 8:07.37, 12:09.67, 16:12.00, 20:14.33, 24:16.63, 28:18.97, 32:21.30, 36:23.60, 40:25.93, 44:28.27. ⚠ Run with the YouTube look-up replaced (it answered from the cached file's length, rounded up like YouTube), because of the bot check below; everything else was the real pipeline (CSV adapter, FFmpeg, `long_cache`). The maintainer reran it fully live (real look-ups) on 2026-09-28: passed. Watching the joins and listening near the end of the long outputs: no stutter, no shift at the joins, lip sync stays right (maintainer check, 2026-09-28).

**Short streams: padded, and warned about past 0.5 s** (maintainer request after the slice 3 review; port change approved 2026-09-28: `ClipInfo.audio_s` / `video_s`, both default `None`). The renderer pads a stream that ends early (silence, or the last frame repeated), which keeps the planned length but could hide a real problem, such as a frozen picture. So `measure()` also reports how much audio and video the measured range really has, and the core warns when either is more than 0.5 s shorter than the clip (padding included): a row warning for a song, one per run for the countdown (it's measured once). [found]
- Audio: the decoded length, from FFmpeg's `-progress pipe:1` report (the last `out_time_us=`) in the same run that finds the peak. ⚠ `volumedetect`'s own `n_samples` read **0** with FFmpeg 8.0.1 (the decoders give float samples), so it's not used.
- Video: the stream's start + length from ffprobe, limited to the range. A cover image (`attached_pic`, e.g. in an MP3) doesn't count as video. No stored length (some `.webm`) → `None` → no warning.
- Real files are far below the threshold: YouTube countdown `.webm` audio 5.336 s of 5.341 s; `.mp4` video 5.320 s of 5.387 s; songs 41–64 ms short at most.
- Fixtures `tests/fixtures/short/video_4s_audio_6s.mp4` and `video_6s_audio_4s.mp4` (FFmpeg `testsrc` + `sine`; recipe in `tests/test_short_streams.py`). The 4 s AAC tone decodes to ~4.01 s (encoder padding).

**YouTube bot check.** After ~20 live runs and several hundred look-ups in one morning, look-ups failed with `Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies …`. The countdown look-up failed after 2 retries and the run stopped, as designed. Then plain `HTTP Error 429: Too Many Requests`, still after ~15 min. Not caused by this slice's code; not retried further, to let the limit expire. yt-dlp's suggested fix is cookies (`--cookies-from-browser`), which the program doesn't support; if this happens at a real event, that's a maintainer decision (HANDOFF). [found 2026-09-28]

**Tests.** 67 tests (+21). `test_audio_length.py` (20 Opus countdowns keep the planned length, ±0.02 s; the fixture still has its Opus gap), `test_output_naming.py` (fake processor: success, length mismatch, failure after / before writing, `_FAILED_2`, leftover cleanup, locked leftover on Windows), `test_crossfades.py` (the rule, no overlapping fades, short countdown, short song, 3-frame floor), `test_chunks.py` (split maths, cut inside the solo part, one-frame solo part, 3 chunks rendered with the chunk size patched to 2: length, A/V within a frame, progress, temporary files gone).

## 17. Slice 4 — setup and run scripts (2026-09-28, branch `slice-4-setup-run`)

Windows 11, i5-6400, home connection. Pythons installed side by side: 3.11.9, 3.12.10, 3.13.15 (per-user, via winget), 3.14.0 (`C:\Python314`). System FFmpeg: `C:\Program Files\FFmpeg\bin\ffmpeg.exe`, version `N-121522-gd01608e022-20251026` (a dev build with no version number).

**Layout.** The shell scripts own "get a suitable Python" (maintainer decision 2026-09-28); everything after that is one Python script:
- `setup_once.bat` / `run.bat` → `tools\find_python.bat`; `setup_once.sh` / `run.sh` → `tools/find_python.sh` (sourced). They read `python-range.txt`, look for the newest Python in the range, and if there is none, offer the newest version in the range: `winget install --id Python.Python.3.13 -e` (Windows) or `brew install python@3.13` (Mac), only after a yes; on Linux they print the command. No winget / declined → python.org.
- `tools/env_setup.py setup | run [args]`: standard library only, always started with a Python in the range, **never with the venv's own** (it may delete `.venv`, which Windows refuses while that Python runs; it checks and refuses).
- `LARB_PYTHON_RANGE` (environment variable) overrides the file, for testing only.

**Finding Python on Windows.** [found]
- `py -3.13 -c "import sys; print(sys.executable)"` gives the full path; a missing version prints nothing on stdout, so the `for /f` loop just moves on.
- ⚠ With a venv **activated** in the terminal (VS Code does it by itself), a bare `py` picks the venv (`py -0p` marks it `*`). The scripts always ask for a version (`py -3.x`), which ignores the venv.
- ⚠ `python` / `python3` on this PC are only the Microsoft Store placeholders (`WindowsApps\python.exe`). With arguments they print a message on stderr and fail, so the fallback "`python` on PATH, if in range and not a venv" simply finds nothing. The scripts never rely on bare `python` otherwise.
- The new Python install manager (python.org's default from 3.14) also provides `py`; how it answers `py -3.13` when 3.13 isn't installed was not tested. [verify]
- ⚠ **winget's error codes are negative** (e.g. `0x8A150014`, "No package found"), so `if errorlevel 1` misses them: a failed install was reported as installed. Use `if not "%errorlevel%"=="0"`. [found]
- `pause` with no console input (automated runs) returns at once, so `setup_once.bat` always pauses at the end (double-click: the window stays readable), and `run.bat` pauses only when started without arguments. [found]
- Folder names with spaces work (tested). `%~dp0` is kept out of `( )` blocks, so brackets in a folder name can't break them (not tested).

**The venv.** `.venv` is rebuilt when it's missing, its Python doesn't start, or its Python is outside the range; never otherwise ("rebuild, never repair", §2). The pinned libraries are installed when `.venv/larb-installed.txt` doesn't hold the hash of `requirements.txt`, so running setup again skips them, and a changed `requirements.txt` (after a `git pull`) is installed by the next `setup_once` or `run`. [found]
- `run`'s automatic rebuild does the same as setup, including the static-ffmpeg download, but asks nothing (no install offers). Without the download, a rebuilt venv would have no FFmpeg on a PC without a system one. The *program* still never downloads (below).
- `shutil.rmtree(onerror=…)` prints a deprecation warning on 3.12+; the script uses `onexc` there.

**yt-dlp update.** `pip install -U yt-dlp --retries 1 --timeout 10` on every setup and run.
- ⚠ **With yt-dlp already installed, pip exits with 0 when PyPI can't be reached** (it only prints `WARNING: Retrying (...)`). So the script decides from the output: with `-q`, a good run prints nothing; `Retrying` or `Could not fetch URL` means no connection → warning, continue with the installed version. Not installed at all → stop. [found]
- Simulation: `PIP_INDEX_URL=http://127.0.0.1:9/simple` makes only pip fail, so the rest of the run can still reach YouTube. `HTTPS_PROXY=http://127.0.0.1:9` makes everything fail (pip, static-ffmpeg download).

**A run never downloads FFmpeg** (fix approved 2026-09-28). `find_ffmpeg()` used `get_or_fetch_platform_executables_else_raise()`, which starts the 200 MB download when the binaries are missing. static-ffmpeg has no "path only" call, but it writes `bin/<platform>/installed.crumb` when a download is complete. `_static()` now uses the binaries only if that file exists (then the same call just returns the paths); `fetch_static()` is the download, called only by setup. Test: `test_locate.test_run_never_downloads_static_ffmpeg`. [found]

**FFmpeg in setup.** `fetch_static()`, then `find_ffmpeg()` through the venv's Python, so setup and the program use one rule. A failed download prints one line (not the requests traceback) and falls back to the system FFmpeg. None usable: Windows offers `winget install --id Gyan.FFmpeg -e` (declined → gyan.dev), Mac `brew install ffmpeg`, Linux prints `sudo apt install ffmpeg` with a warning that the distribution's FFmpeg may be older than 7.1. [found on Windows, both branches: download blocked → system dev build accepted; system FFmpeg also hidden from PATH → offer shown, "n" installs nothing]

**Measured (Windows).** [found]

| Step | Time |
| --- | --- |
| `setup_once.bat`, fresh clone (Python 3.13), incl. static-ffmpeg download | **165 s** |
| same, 3.11 / 3.12 clones | 124 s / 115 s |
| `setup_once.bat` again, nothing to do | **4 s** |
| `run.bat` with a 3.14 venv → rebuilt with 3.13, then the live sheet (songs cached) | 149 s |
| `run.bat`, live sheet, 3 songs, audio, empty cache | 22 s (output 139.02 s = planned) |

**Python versions.** All 75 tests pass on **3.11.9, 3.12.10 and 3.13.15** (each in a clone set up by `setup_once.bat` with `LARB_PYTHON_RANGE` set to that one version; ~62 s each), so the range stays `3.11-3.13` and 3.13 is the one offered. 3.14 builds a venv and installs every pin (57 s), but it's outside the range; tests not run on it. [found]

**Pins.** On 3.11, `keyring` and `jaraco.context` also pull in `importlib_metadata`, `zipp` and `backports.tarfile` (not needed from 3.12): pinned with `; python_version < "3.12"`. After that, `pip freeze` on 3.11 shows nothing unpinned but yt-dlp. [found]

**Line endings and permissions.** `.gitattributes`: `*.sh text eol=lf`, `*.bat text eol=crlf`, whoever commits. ⚠ A commit from Windows has no executable bit, so a Linux clone said `./setup_once.sh: Permission denied`: set in git with `git update-index --chmod=+x setup_once.sh run.sh` (mode `100755`). `tools/find_python.sh` is sourced, so it needs none. [found]

**Linux (WSL, Ubuntu 26.04.1 LTS), fresh clone in `~/`** (not `/mnt/d`). [found 2026-09-28]
- ⚠ **Ubuntu 26.04 ships only Python 3.14** (outside the range), and without `ensurepip` (venv) and tkinter. With no Python in the range, `setup_once.sh` printed `sudo apt install python3.13 python3.13-venv python3.13-tk`, plus the deadsnakes line for when apt can't find it: `sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update`. deadsnakes has `python3.13`, `-venv` and `-tk` for 26.04 ("resolute"). The maintainer ran both; the scripts never use sudo.
- `setup_once.sh`: **208 s** (static-ffmpeg fetched `v8.0/linux.zip`: FFmpeg `n8.0.1-48-g0592be14ff-20260116`). Again: 2 s. tkinter check: `tkinter: available` (python3.13-tk installed). If it were missing, it prints `sudo apt install python3.13-tk`; not seen live, since the only Python without it was the out-of-range 3.14.
- `run.sh <live sheet>`: 34 s, audio output 139.02 s = planned (one intermittent 403, fixed by the usual retry, §9). All 75 tests pass (1 skipped: the Windows-only locked-file test).
- Unpinned on Linux: `SecretStorage`, `jeepney` (from `keyring`), `cryptography`, `cffi`, `pycparser` (from `SecretStorage`). Pinned from this environment with `; sys_platform == "linux"`; after that only yt-dlp is unpinned. On Windows the markers skip them (checked). Mac: `keyring` needs nothing extra there, but not checked on a real Mac.
- The executable bit on the `.sh` files had to be set in git (above). LF endings in the clone confirmed (`file`: no CRLF).

**Not tested:** Mac (no Mac: Homebrew offer, `python-tk@3.13` hint); the Windows "yes" path with a real install (tested only with a version winget doesn't have, which fails → python.org); the Windows tkinter-missing message.

## 18. Slice 5, Part A — what the GUI needs from the core (2026-09-29, branch `slice-5-gui`)

**Port changes (approved by the maintainer 2026-09-29):** `MediaSource.cancel()`, `MediaProcessor.cancel()` and `StoppedError`; `LogEvent.activity` (`Activity`: `key`, `label`, `started`). Also approved: `larb/app.py` is now the one place that wires adapters to ports (the CLI uses it; the GUI will).

**Stopping a run.** The GUI calls `Pipeline.stop()` from its own thread. It sets the pipeline's flag and calls both `cancel()`s; `run()` then raises `StoppedError("Stopped by the operator")`. [found: offline tests, `tests/test_stop.py`]
- The core checks the flag between stages, before each row's look-up and before each download; queued rows and downloads never start. Retry pauses are `Event.wait()`, so a stop cuts them short (test: < 0.9 s into a 1 s pause).
- **A look-up already running finishes** (yt-dlp has no way to interrupt `extract_info`); the maintainer accepted the wait (2026-09-29). The sheet fetch (one request) isn't interrupted either.
- **yt-dlp:** `cancel()` sets a flag that a `progress_hooks` / `postprocessor_hooks` entry checks; it raises `yt_dlp.utils.DownloadCancelled`, yt-dlp's own "stop now" exception, which its extraction wrapper re-raises unchanged (checked in yt-dlp 2026.08.19, `YoutubeDL._handle_extraction_exceptions`). The adapter turns anything raised after a stop into `StoppedError` and never falls back to a fresh look-up then. **Live:** a real 720p download cancelled after 1 s raised `StoppedError` at 1.0 s and left `oKBwWQI-IoI_v720.f136.mp4.part`; `remove_leftovers` deleted it. [found 2026-09-29]
- **Leftovers:** the core removes every `<stem>.*` file of an interrupted download (`cache.remove_leftovers`, same name rule as `clear_cache`), and logs each. Finished downloads stay cached.
- **FFmpeg:** `run_tool` now uses `Popen`, reads stdout/stderr on two threads (FFmpeg blocks if a pipe fills), and on a stop writes `q` to FFmpeg's stdin, then kills it after `QUIT_GRACE_S` = 5 s. `communicate()` can't be used: it closes stdin, and `q` could no longer be sent. Measured with `-re` generators, stop at 2 s, 3 runs each: MP3 encode exits **0.11–0.17 s** after the stop, H.264 720p **0.42–0.47 s**; every partial file stays readable (ffprobe: 2.16–2.20 s). A kill (Windows `TerminateProcess`) would leave an MP4 without its index. [found 2026-09-29]
- A stopped render that wrote something is renamed `_FAILED` like a failed one; in video mode the output file is only written by the final join, so a stop during the chunks leaves nothing there. Chunk, audio and graph files are deleted (graphs are kept only for a real failure).
- Tests: stop during look-ups (the running one finishes, the other 5 never start), during downloads (finished file kept, `.part` removed, the queued download never starts), during a retry pause, during a 3-chunk video render with the audio pass running beside it (real FFmpeg), `_FAILED` after a stopped render that wrote something, stop before `run()`, and `run_tool` alone. Checked against broken builds: with `Pipeline.stop()` not cancelling the media source, or `FfmpegProcessor.cancel()` doing nothing, the download and render tests fail.

**Download markers.** One `started` and one ended `Activity` per download (countdown included), keyed by the cache stem, emitted at DEBUG in stage `download`: the log file has them, the console and the GUI's log don't show them. Retries don't add lines; a failure or a stop still sends the end (`finally`). [found: `tests/test_markers.py`]

**Progress.** Besides checking (§14) and video parts (§16): `download` `(0, N)` on the INFO line that starts the stage, then `(done, N)` per finished download (a failed one counts as done) at DEBUG; `measure` `(n − 1, N)` before each song, at DEBUG. [found]

**Row range, open edges.** `RowRange.first` / `last` may be `None`; `row_range_from_fields("3", "")` = row 3 to the last row with content, `("", "10")` = first song row to 10, both empty = `None` (all rows). Non-numbers, backwards and header rows are refused with the same messages as `--rows`. The command line keeps `first-last` (`--rows 3-` is refused). [found]

**Folders.** `settings.resolve_folder`: empty = `workspace/<name>`; relative = from the project folder (fixes the SPEC §14 known issue: `workspace/output` no longer becomes `workspace/workspace/output`); absolute as is. `ensure_folder` creates it at run start, before any download, and names the folder if it can't (e.g. a file in the way, no permission). `folder_setting` gives what the GUI saves: `""` when the shown full path is the default folder, so `config.toml` survives moving the project folder (maintainer decision 2026-09-29). [found]

**Crossfade.** Default 0.8 (`models.DEFAULT_CROSSFADE_S`, `config/example.toml`). An existing `config.toml` keeps its own value (loading only fills in missing keys). `settings.correct_crossfade` for the GUI field: not a number (blank, letters, `nan`) → 0.8; below 0.1, 0 and negatives included → 0.1 (the 3-frame floor; maintainer decision 2026-09-29, revised after Part A: at first only 0 or less was raised); over 10 (and `inf`) → 10; `1,5` is read as 1.5. `config.toml` validation is unchanged (any value above 0). [found]

**Tests.** 109 (+34), ~90 s. Tests whose expected lengths assume 1 s crossfades now set `crossfade_duration_seconds=1.0` explicitly instead of relying on the default.

**Live, no regression:** `python -m larb <live sheet>` (audio, all cached): 140.02 s = planned, with the operator's `config.toml` at 0.8; `config.toml` unchanged by the run. [found 2026-09-29]

## 19. Slice 5, Part B — the window (2026-09-29, branch `slice-5-gui`)

Windows 11, 1920×1080 at 100 % scaling, Tk 8.6 (Python 3.12 venv). WSL: Ubuntu 26.04, Python 3.13, Tk 8.6, WSLg.

**Layout.** `src/larb/gui/`: `state.py` (every decision, no Tkinter: what's enabled, the progress label, counts, filter, active downloads, fields → run; tested offline), `runner.py` (worker thread + queue), `window.py` (widgets only), `widgets.py`, `theme.py`. `python -m larb` without arguments opens it; with arguments the CLI runs as before.

**Recipes and quirks** [found]:
- **Coloured buttons are `tk.Label`s** with click/hover bindings (`widgets.ColorButton`): `tk.Button` ignores `bg` on Mac, and ttk buttons can't be coloured per button with Windows' native theme. ttk widgets use the `clam` theme, which accepts colours on every OS; the NEON radio dot is `indicatorcolor` mapped on `selected`.
- ⚠ **Never name an attribute `_w` on a Tk widget subclass**: it's Tkinter's internal widget path. `SweepBar` did, and every canvas call failed with `invalid command name "180"`.
- **Log filter = Text-tag `elide`**: each line is tagged `level_<LEVEL>`; the filter hides tags instead of rebuilding the text, so a 300-song log filters instantly.
- ⚠ **Auto-follow must be decided once per batch.** Checking `yview()` before each inserted line reads a stale value after the first insert (Tk recomputes it only when it redraws), so a burst of lines stopped the following. Now `_poll` checks once, inserts the batch, then scrolls.
- ⚠ **Don't touch widgets after `root.destroy()` in the same callback**: closing during a run destroys the window from `_poll`; its final scroll then hit a dead widget.
- **Dialogs** are one modal `Toplevel` (`widgets.ask`), dark like the window, with the exact buttons GUI.md names; the default is focused (Enter); Escape and the window's close button give a separate "escape" answer (Cancel for "Save your changes?"). `messagebox` can't label its buttons.
- **Stopped label**: a long reason (a missing column lists every header found) takes the bar's place and wraps; a fixed width cut it off.
- **Windows title bar** stays in the system's accent colour on this PC: `DwmSetWindowAttribute(DWMWA_USE_IMMERSIVE_DARK_MODE)` is set, but Windows ignores it when "Show accent colour on title bars" is on. Left alone (it's the operator's system setting); overriding it would need `DWMWA_CAPTION_COLOR` (Windows 11 only).
- **DPI**: `SetProcessDpiAwareness(1)` before `Tk()`, so text stays sharp at 125/150 % (not tested at other scalings: this PC is 100 %).
- **Minimum size** = the requested size after layout (637×755 here); a smaller geometry is refused; extra height goes only to the log panel. Room for `max_parallel_downloads` download lines is reserved, so the log doesn't jump when they appear.

**`run.bat` without arguments** restarts itself with `start "LARB - Spicy (console)" /min cmd /c call "%~f0"` (guard: `LARB_MINIMIZED`), then `env_setup.py run` → `python -m larb`. The console closes after a normal exit and pauses after a failure. ⚠ Give the console a **different title** from the window: with the same title the taskbar shows two identical entries (and a test closed the wrong one). ⚠ Git Bash's `sed -i` rewrote `run.bat` with LF line endings; edit `.bat` files with something that keeps CRLF (`.gitattributes` fixes the committed copy, not the working file). Measured: window visible **8 s** after starting (includes the yt-dlp update check); closing the window left no process behind. [found]

**Fonts.** Windows 11: Thai, Korean and Japanese all render through Tk's font fallback from Segoe UI (no font list needed). **WSL Ubuntu 26.04 has no font for any of the three** (`fc-list :lang=th` empty): they showed as boxes. Tested without changing the system: `apt download fonts-noto-cjk fonts-tlwg-loma-otf fonts-tlwg-garuda-otf`, unpacked under `/tmp`, used by one process through `FONTCONFIG_FILE` → all three render (then removed). `fonts-thai-tlwg` is a metapackage (its `fonts-tlwg-*` dependencies pull the real `-otf` fonts), so the operator command is `sudo apt install fonts-thai-tlwg fonts-noto-cjk` (fonts-noto-cjk is a ~61 MB download). `setup_once` now warns and prints it (`env_setup.check_fonts`). The Fedora package names (`google-noto-sans-thai-fonts google-noto-sans-cjk-fonts`) are not tested. [found 2026-09-29]

**Live runs from the window** (live sheet, 3 songs; scripted through the real `Window` with a copy of the settings, so `config/config.toml` was never written): [found 2026-09-29]

| Run | Result |
| --- | --- |
| Audio, all cached | label Starting → Reading the sheet → Preparing the countdown → Checking n / 3 → Rendering → **Finished**; 140.02 s = planned; cache reminder last in the log; Open file / Open folder enabled |
| Video, 3 new downloads | countdown and song download lines with timers and the sweep; downloads 67 s, render 38 s; Finished |
| Private sheet | pop-up "The sheet can't be read (HTTP 401) …", RED "Stopped: …", window unlocked |
| Header-mismatch sheet | pop-up naming `ศิลปิน` and the headers found; the RED label wraps |
| Stop while downloading (video, empty cache) | confirmation with Keep running as default; run ended **1.8 s** after Stop; cache: only the finished countdown; no `.part`; no output; unlocked |
| Stop while rendering (video, cached) | ended **3.3 s** after Stop; no `.rendering`, no `_FAILED` (a video writes the output file only in its final join), tmp empty |
| Close during a run → Stop and close | window closed ~2 s later, once the run had ended; log shows "Stopped by the operator" |
| Crossfade field | `abc`, blank, spaces → 0.8; `0`, `-3`, `0.05` → 0.1; `15` → 10; also on leaving the field |
| Close with unsaved edits | Cancel keeps the window; Save writes them (`audio_only`, crossfade 1.5) |
| Save to `C:\Windows\System32\…` | refused before saving or running: "Can't create the output folder … Access is denied"; the log stayed empty |
| Save to a missing folder | created; output there; saved as its full path (the default folder is saved as `""`) |

**Screenshots for checking: capture only the program's window.** ⚠ The first harness used `CopyFromScreen` on the window's rectangle; when another window was brought to the front, it captured that instead (deleted). Use `PrintWindow(hwnd, dc, PW_RENDERFULLCONTENT)` with the Tk frame's handle (`int(root.wm_frame(), 16)`): only that window's pixels, even when covered. ⚠ `PrintWindow` asks the window's own thread to paint, so the Tk loop must keep running meanwhile (start PowerShell with `Popen` and call `root.update()` until it ends), or both wait forever. WSLg windows are `msrdc.exe` windows titled `… (Ubuntu)`; `PrintWindow` works on them too.

**Not done / not tested:** Mac (only the mirrored row, forced with the developer switch `LARB_GUI_MAC=1`); scalings other than 100 %; a real click on Open file / Open folder (called with the right paths; the system call itself not exercised); keyboard-only use beyond Enter / Escape in dialogs; a full run from the window in WSL (opened and displayed only).

**Tests.** 135 (+26), ~90 s: `tests/test_gui_state.py` (controls per phase, fields → run, the progress label through every stage and both endings, filter and counts, active download lines by key, texts, bottom-row order, the worker with a fake pipeline: stop reaching it, stop before it exists, an unexpected error still ending the run). Tkinter widgets themselves are not unit-tested.

**After review (2026-09-30): title, icons, title bar, radios, shortcuts.** [found unless marked]
- **Title** "LARB - Spicy"; the console "LARB - Spicy (console)". Pane titles removed (maintainer decision).
- **Taskbar identity**: `SetCurrentProcessExplicitAppUserModelID("LarbSpicy.RandomDanceCombiner")` **before** `Tk()`. Without it Windows files the window under Python and the taskbar shows Python's icon.
- **Two icons** (`gui/system.py`): `WM_SETICON` with `ICON_SMALL` = `assets/icon_titlebar.ico` (white) and `ICON_BIG` = `assets/icon_taskbar.ico` (accent), each loaded with `LoadImageW` at the size Windows asks for (`GetSystemMetrics(SM_CXSMICON / SM_CXICON)`: 16 and 32 px at 100 %). `wm iconbitmap` can't do this: it takes one `.ico` for both. Dialogs get the same. Read back from the live window (`WM_GETICON`): the small icon is the white 16 px one, the big icon the accent 32 px one. The taskbar itself was not screenshotted (it shows the operator's other apps): maintainer check.
- **Title bar colour**: `DwmSetWindowAttribute(DWMWA_CAPTION_COLOR = 35, COLORREF 0x0088008B)` = DARK `#8B0088`, and `DWMWA_TEXT_COLOR = 36` white. Windows 11 only; it overrides the "accent colour on title bars" setting. Older Windows refuses attribute 35 and keeps the dark-mode request (20, or 19 on old Windows 10 builds); nothing is reported. `DwmGetWindowAttribute` can't read attribute 35 back, so it was checked on a screenshot.
- **Linux icon**: `iconphoto(True, PhotoImage(icon.png))` (default for later dialogs too). In WSL the PNG loads (256×256) and Tk accepts it, but WSLg draws its own generic icon in the frame and gives Windows no icon for the window, so the result can't be seen there: check on a real Linux desktop.
- **Radio circles** (`clam`): `indicatorbackground` is the circle, `indicatorforeground` the dot. Now white when usable, `FIELD` grey when disabled (`style.map`). The `indicatorcolor` option used before doesn't exist in `clam` and did nothing.
- **Ctrl+C / V / X / A / Z in any keyboard language** (`gui/shortcuts.py`). Tk matches `<Control-c>` by the typed character; with the Thai layout the C key types แ, so copy and paste did nothing. Recognized now by key code, one table per OS: Windows virtual-key codes (A 65, C 67, V 86, X 88, Z 90), Linux X key codes (A 38, C 54, V 55, X 53, Z 52); Ctrl+Alt (AltGr on Windows) is left alone. The Tk virtual event (`<<Copy>>` …) is generated, so the result is exactly Tk's own.
  - ⚠ **Own binding tag, in front of the class tag.** On Linux the `TEntry`/`Text` classes bind Emacs-style keys (`<Control-Key-a>` = line start, `<Control-Key-k>` …); Tk runs only the most specific binding per tag, so a generic `<Control-KeyPress>` on the class never ran there. `install()` runs after the window is built and puts the tag on every text widget.
  - **Real layouts on Windows**: the Thai, US, Korean and Japanese layouts were activated **in a test process's own thread only** (`LoadKeyboardLayoutW` + `ActivateKeyboardLayout`, Ctrl set with `SetKeyboardState`), then `WM_KEYDOWN` for A, C and V posted straight to the field's own window (nothing sent to the foreground). Without the fix: Thai copies and pastes **nothing**; US, Korean and Japanese work (their keys still type Latin letters with the IME off). With the fix: all four copy and paste. Layouts not installed before were unloaded again.
  - Linux: tested with generated events in WSL (all 34 GUI tests pass there); a real Thai X keymap was not tried (no `xdotool` and no sudo).
  - Tk 8.6 text fields have no undo, so Ctrl+Z does nothing in them in any language (English included). Mac keeps Tk's own Command bindings (not tested, no Mac).
  - ⚠ Tk on Windows can't `event_generate` a keysym the active layout doesn't have (`no keycode for keysym "Thai_saraae"`), and key events go to the focused widget, which a withdrawn window can't have: the tests use an off-screen window and another letter in place of the Thai character.
- **WSLg** once lost its X socket after WSL restarted (`couldn't connect to display ":0"`); it came back by itself within a minute. `wsl --shutdown` would also stop Docker Desktop's distro, so it wasn't used.

**Tests.** 143 (+8): `tests/test_shortcuts.py` (the key tables, AltGr and other keys left alone, NumLock ignored on Windows; in real widgets: copy and paste with another letter typed, select all, English Ctrl+V pastes once, Ctrl+K does nothing, copy from a disabled text area like the log).

## 20. Slice 6 — reliability (2026-10, branch `slice-6-reliability`)

**Port changes (approved by the maintainer 2026-10-01):** `MediaSource.media_id(url)` (the video's ID from the URL alone, no request); `RateLimitedError` (bot check / HTTP 429), raised by `lookup` and `download`; `ClipInfo.has_video` and `Segment.has_video` (a clip with no picture).

**Real Ubuntu 24.04 PC** (the maintainer's test, 2026-09; not a VM, fast network). [found]
- Python 3.12.4 was already installed (in range); setup used it.
- tkinter was missing; the command setup printed fixed it on the first try.
- The window icon doesn't show. Normal on that desktop (§19: the icon is set; the desktop decides whether to draw it).
- **Open file** did nothing until a media player was installed; the console said "no media player found". After installing VLC it worked.
- Output: audio and mirrored video both worked. 5 songs took well under a minute.
- ⚠ **A cached countdown still triggered the bot check**: every run looked up the countdown and every row on YouTube, even when all were cached. On the fast connection, rows ran out of retries and were skipped. Re-running a few minutes later recovered the missing song. This is what cache-aware checking and the rate-limit stop in this slice address.

**A venv whose Python was uninstalled** (Windows, 2026-10-01). The maintainer had uninstalled Python 3.12; `.venv` still pointed at it (`No Python at '...Python312\python.exe'`). [found]
- `run.bat` noticed it and announced the rebuild: `Rebuilding the environment, including a one-time FFmpeg download (~200 MB)...`, then `The .venv folder is broken (its Python doesn't start): building it with Python 3.13`.
- `setup_once.bat`, with the venv broken the same way again (`pyvenv.cfg` pointed at the missing Python): `The .venv folder is broken (its Python doesn't start)`, rebuilt with 3.13, FFmpeg downloaded, **172 s**.
- ⚠ **An interrupted rebuild skipped FFmpeg.** The first `run.bat` built the venv, then pip failed (a network error), so the run stopped. The next `run.bat` found a venv that starts, installed the libraries, and **never downloaded FFmpeg**: the program would have used the system FFmpeg, or stopped on a PC without one. Fixed: when `run` installs the libraries, it also checks FFmpeg (instant when the binaries are there). Checked by recreating that state (stamp file removed, no FFmpeg): the next `run.bat` downloaded it. This also covers a future `static-ffmpeg` pin change.
- All 143 tests pass on the rebuilt 3.13 venv.
- ⚠ Claude's sandboxed shell couldn't reach PyPI (`SSLError ... UNEXPECTED_EOF_WHILE_READING`) although `curl` to PyPI worked; outside the sandbox pip worked. If a future session sees that, it's the session's network, not the setup script.

**Black screen for a clip without a picture** (video mode). [found 2026-10-01]
- `measure()` sets `ClipInfo.has_video` from ffprobe: a video stream that isn't a cover image (`attached_pic`). An `.mp3` with embedded cover art has a video stream with `attached_pic=1`: **no picture** (maintainer decision 2026-10-01: black, not the cover).
- The core copies it to `Segment.has_video` and warns: the countdown once per run (it's measured once, however many times it's used), a song as a row warning. Audio mode never warns.
- The renderer draws `color=c=black:s=WxH:r=30:d=<len>` for that segment, through the same `setpts`/`tpad`/`trim` tail as a real picture, so its length is exact. In a video-only pass (the chunks) the file isn't opened at all; the input numbers in the graph come from a segment → input map. The audio pass is unchanged.
- Before this, an `.mp3` countdown in video mode failed in FFmpeg (`Error binding filtergraph inputs/outputs`), and a cover-art `.mp3` rendered with the wrong frame count (`210 frames but should have 590`): both seen by running the new tests against the old behaviour.
- Fixture `tests/fixtures/countdown/cover_art.mp3` (129 KB): the countdown `.mp3` with a red 64×64 cover; recipe in `tests/test_black_screen.py`. ⚠ Making it in one FFmpeg run with `-frames:v 1` cut the **whole output** to one frame (0.036 s): make the image first, then attach it.
- Live (video, live sheet, `--countdown tests/fixtures/countdown/!countdown.mp3`): 140.00 s vs 139.99 s planned, one warning for three countdowns; frames checked: countdowns black, the song a (mirrored) picture. Output for the maintainer to view: `workspace/output/2026-10-01_194146.mp4`.

**Render progress.** [found 2026-10-01]
- FFmpeg's `-progress pipe:1` prints `out_time_us=` about twice a second; `run_tool` now reads stdout line by line and hands each value to an `on_progress` callback (still collecting the text, so `measure()` reads its own report as before). Works with `-nostats`.
- The adapter reports `LogEvent.progress = (done, total)` in **milliseconds of planned output**: DEBUG at most once per whole percent, INFO when a 10 % mark is passed (the terminal's line every 10 %; a fast audio render jumps, e.g. 10 → 30 %, so some marks are skipped, never repeated). Video: the chunks are rendered one after another, so done = finished chunks + the current chunk's time; the audio pass beside them isn't counted (it finishes well within the chunks' time). After the render the adapter reports the total itself: FFmpeg's last report can be a few ms short.
- Steps without numbers send an INFO without progress: `video part n/N written; checking it`, `joining the video parts and the audio`, plus the core's own render lines. The "Rendering part n / N" progress of slice 5 is gone.
- GUI: `ProgressView.fraction = None` means sweep. That's every step without numbers, and also a stage's `(0, N)` (nothing done yet), so the bar is never empty and still. The overall bar is now a canvas (`widgets.OverallBar`) that fills NEON or sweeps the DARK→NEON gradient; the ttk progress bar and its style are removed.
- Checked by feeding the real pipeline's events (live sheet, cached, audio and video) into `ProgressView`: no state with an empty, still bar in either mode; video showed ~80 steps from 1 % to 100 %; audio (3.4 s render) ~7.

**Cache-aware checking.** [found 2026-10-01]
- `MediaSource.media_id(url)`: the yt-dlp adapter uses `YoutubeIE.get_temp_id(url)`, yt-dlp's own URL pattern, no request. It gives the same ID as a look-up for `watch?v=`, `&list=RDMM…`, `youtu.be/…?si=`, `music.youtube.com`, `/shorts/`, `m.youtube.com`, `watch?app=desktop&v=`; `None` for a truncated ID, a playlist, another site. `YoutubeIE.suitable()` is **False** for `&list=` links (the playlist extractor claims them), so it isn't used. Any exception → `None` → looked up as before. Importing the extractor took 14 s **once** on a fresh venv (compiling); normally instant.
- The core checks the cache before the look-up: a row whose file for this run's mode exists is measured instead (`measure(file, 0, 0.1)`, length only). The strict "end past YouTube's length" check is skipped for it: stage 6 applies the usual rules to the exact length (trim within ~1 s with a warning, otherwise a row error; maintainer decision 2026-10-01). The countdown URL likewise.
- Live, live sheet: audio run 1 (empty cache) 4 look-ups, 23 s; **run 2: 0 look-ups** (`3 checked from the cache, 0 looked up`; no `looked up … in` line in the log file), 6 s. Video run with only audio files cached: all 3 rows and the countdown looked up (the other mode doesn't count), 202 s (downloads 2.5 min, a slow evening); video run 2: 0 look-ups, 35 s. Lengths: audio 140.02 = 140.02 s, video 140.17 vs 140.16 s.
- A cached row has no YouTube title; the log uses the sheet's title, as before.

**403 retry waits: measured** (maintainer's home connection, 2026-10-01 19:45–20:00, 15 min time box). Audio downloads through the real yt-dlp adapter, each a fresh look-up + download (as a core retry is), 3 at once, cycling through the Big Sheet's 95 videos; files deleted after. On a 403 the first retry waited 0, 2 or 5 s (rotating), a second retry twice that. Raw: `workspace/slice6/m403/results.csv`; the script was throwaway. [found]

| First wait | 403s | Fixed by retry 1 | Needed retry 2 |
| --- | --- | --- | --- |
| 0 s | 4 | 4 | 0 |
| 2 s | 4 | 3 | 1 (fixed after 4 s more) |
| 5 s | 4 | 4 | 0 |

- 309 downloads, **12 first-try 403s (3.9 %)**, in line with §9 (4.4 % for audio). **All 12 recovered**, 11 on the first retry. No download failed for good. 8.8 s per download (a slow evening; the same songs took 2–4 s in §9).
- **No bot check** in 309 requests + the 4 live runs before it (~330 requests in 25 min). So the limit seen on 2026-09-28 needed more than this, or a fast connection (the Ubuntu PC).
- **The sample can't rank the waits:** 4 cases each, and the one double 403 is 1 case. Nothing shows that waiting longer helps, or that it hurts. As agreed with the maintainer for an unsettled sample, the fallback is built: **2 s, 4 s, 8 s, each ±25 %** (`RETRY_BASE_S`, `RETRY_JITTER`). With the default `max_retries = 2`, a song waits at most 2.5 + 5 s. The randomness spreads parallel retries; this measurement couldn't show whether that matters (no two 403s came within a second of each other).
- Stop during a retry wait still ends at once (`test_stop.test_during_a_retry_pause`, now a ~2 s wait, ended in < 0.9 s).

**Rate limit (bot check / HTTP 429).** The adapter turns "confirm you're not a bot", "HTTP Error 429" and "Too Many Requests" into `RateLimitedError`, checked before the permanent / retryable sorting. It isn't retried, and a download with reused info that hits it doesn't fall back to a fresh look-up. The core sets a flag: queued look-ups and downloads don't start, retry waits in progress give up after their wait, running work ends (a finished download stays cached; leftovers of an interrupted one are removed), then the run raises `RateLimitedError` with the message and "N of M song(s) are downloaded and cached" (counted with `media_id`, no request). Rows that were never checked aren't row errors. The terminal prints it as the ERROR line; the GUI shows the aborted-run pop-up. **Not seen live** in this slice (no bot check happened); tested with a fake source (`tests/test_retries.py`).

**Tests.** 174 (+31), ~131 s (was ~93 s: the existing tests that exhaust their retries now really wait 2 + 4 s). New: `test_black_screen.py` (`.mp3` countdown and cover-art countdown black, one warning, sound kept; a song without a picture; audio mode silent), `test_cache_aware.py`, `test_retries.py`, `test_open_output.py` (opener with a simulated missing app on Windows and Linux; the real window's pop-up and warning), plus progress in `test_chunks.py` and `test_gui_state.py`, and the adapter's rate limits and `media_id` in `test_ytdlp_reuse.py`. Checked against the old behaviour: with `has_video` forced to True, the three video black-screen tests fail.

**Open file / Open folder failing.** `gui/opening.py`: Windows `os.startfile` raises at once (no app: WinError 1155 "No application is associated…"); Linux/Mac `xdg-open` / `open` say it only through the exit code and stderr, so they're waited for (≤ 30 s) on a thread, and the window checks every 200 ms. Failure → pop-up ("No app is set to open .mp4 files. Install a media player, or use Open folder." + the system's reason) and a WARNING in the window's log. Tested with a simulated missing app, on the real `Window`. **Not tested** with a real missing app (this PC has one; the Ubuntu PC is the maintainer's).

## 21. Slice 7 — Est. Length and remembered inputs (2026-10-01, branch `slice-7-length-memory`)

**Est. Length: the run's own planning, minus YouTube.** `Pipeline.estimate()` goes through the run's steps with the same helpers: `_lock_settings`, `_read_sheet` (stage 2), `_countdown_stage` (stage 3), then `_build_plan` and `RenderPlan.expected_duration_s`. There is no second copy of the length maths. What differs is only where each song's length comes from: [found 2026-10-01]
- **Cached for this mode:** `measure(file, 0, 0.1)` (length only; files measured `max_parallel_lookups` at a time, like the manifest), then `song_clip()`, the clip rule stage 6 also uses (trim within ~1 s, padding clamped to the file, 3-frame minimum). Exact.
- **Not cached:** `song_clip(start, end, None)`: time range plus padding, start clamped at 0, end **not** clamped (the real length is unknown). Off only when the padded end reaches past the real file, by at most the 1 s padding (offline test: 0.49 s, the `sewer` fixture's 66.51 s against an end of 1:06).
- **The countdown** goes through the normal stage 3 (maintainer decision 2026-10-01): an uncached countdown URL is looked up **and downloaded**, with the usual retries and rate-limit stop. Reason: YouTube rounds lengths to whole seconds (the countdown is 5.341 s, YouTube says 5), and the countdown plays before every song, so its error would multiply by the number of songs (~33 s on the 96-row Big Sheet). The run needs the file anyway and then finds it cached.
- Rows a run would skip are left out and counted by reason (`RowProblem.reason`, short texts in `core/manifest.py`): empty URL, unreadable time range, and for cached songs, start past the end, end more than 1 s past the end, clip too short, unreadable file. A video that's gone from YouTube still counts (accepted limit: only a run's look-up finds out).
- Mirror and gain don't change the length, so the estimate's segments leave them neutral; uncached songs get a stand-in path (`Path()`, never opened).
- The estimate writes no log file (an estimate isn't a run, and only the 5 newest logs are kept). Its events reach the window only for the progress label and the countdown's download line; the window logs one INFO line (result) or one ERROR line (failure). An unexpected exception prints its traceback to the console.

**Live, maintainer's sheet (3 songs), fresh cache folder, 2026-10-01:**

| Mode | Estimate, nothing cached | Run: planned / actual | Estimate, cached |
| --- | --- | --- | --- |
| Audio | 140.023 s (4.4 s; countdown downloaded) | 140.02 / 140.023 s | 140.023 s (1.1 s) |
| Video | 140.161 s (5.5 s; countdown downloaded) | 140.16 / 140.167 s | 140.161 s (1.2 s) |

None of these songs' padded ends reach the end of their videos, so even the uncached estimate was exact. The runs found the countdown cached by the estimate (`cached, not looked up`).

**Big Sheet (96 rows), main cache, countdown cached:** estimate audio 3841.2 s (1 h 4 min 1 s) in 1.9 s, video 3845.6 s in 1.5 s; 8 songs measured, 87 from time ranges, 1 row left out (URL is empty); **zero YouTube requests**. Then the real audio run (87 songs looked up and downloaded, 353 s end to end, render 204 s): **output 3841.195 s = the estimate to the millisecond**, although 87 songs were estimated from their time ranges (no padded end reached a video's end). 1 row error (the empty URL the estimate had flagged), 4 row warnings (empty title / artist). No 403, no retry, **no bot check** in 88 requests, so the rate-limit stop is still untested live.

**Remembered inputs.** `gui/memory.py` writes `config/last_inputs.toml` (`sheet`, `countdown`; gitignored) with tomli-w through `toml_settings.atomic_write` (now public), when Run starts (after the window's own checks pass, before the run itself, so a run stopped by e.g. a private sheet still remembers the link). Read with `utf-8-sig`; any error, a wrong type or a missing key → empty field. The row range is never written. Not a port: the core never needs it, only the window. The terminal version doesn't remember anything.

**Tests.** 219 (+45), ~139 s. New: `test_estimate.py` (core, real FFmpeg: estimate vs the plan a real run records, look-up and download counts, countdown retries and rate limit, left-out reasons, `song_clip`), `test_estimate_gui.py` (button state, pop-up and log wording, worker writes no log file, the real window with a fake worker), `test_last_inputs.py` (file round trip, corrupt / missing / BOM, Clear cache on the same folder, the real window: filled on open, saved on Run without rows, not saved when Run is refused).
- Window tests that leave a timer pending (a worker that never finishes) printed `invalid command name "…_tick"` after the root was destroyed. Cancelling with `root.after_cancel()` in cleanup made `destroy()` fail (`can't delete Tcl command`: `after_cancel` deletes the command, `destroy` deletes it again). Cancel with the raw `root.tk.call("after", "cancel", id)` instead.
- ⚠ **`test_shortcuts` errors (5) while the Windows keyboard is on Thai.** `no keycode for keysym "k"`: the tests generate English-letter keys, which Tk can't map under a Thai layout (the test file says so). Same on the untouched `main` code. Loading and activating US English in the test process (`LoadKeyboardLayoutW` + `ActivateKeyboardLayout`) did **not** help, so Tk seems to use the session's layout. Switch the input language to English before running the suite.
