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
- The same `info` dict can be handed to `ydl.process_ie_result(info, download=True)`, so each video's metadata is fetched only once. [found]
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
| 2026-09-27 | Slice 1 live runs: countdown URL, `--rows`, end fade-out, log file | all work; fade reaches ~−30 dB in the last 50 ms (linear), last frame luma ~20 | §13 |
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
- **Each song's metadata is fetched twice** (`lookup` at manifest stage, then again inside `download`), about 1.5–3 s extra per song. The early YouTube check stays (maintainer decision). **Later slice:** the yt-dlp adapter remembers each `lookup` result and reuses it in `download`, with no port change; a retry after a 403 should still fetch fresh metadata (TECH §9).
- **Manifest look-ups run one at a time** (0.5–3 s per row): roughly 5–10 min for ~300 rows before downloads start. **Later slice:** run look-ups in parallel, like downloads. [known]
- The clipped K-pop masters measure a sample peak of exactly 0.0 dB, so peak normalization gives them −1.0 dB. The countdowns get +14 dB.
- Output is rendered to `<name>.rendering.<ext>` and renamed only on success; a failed render leaves no file under the final name. The graph file is kept in `workspace/tmp/` when a render fails, for debugging.
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

**End fade-out.** `RenderPlan.fade_out_s` (port change approved 2026-09-27): the core sets it to the crossfade duration, the FFmpeg adapter adds `afade=t=out:st=L−f:d=f` and `fade=t=out:st=L−f:d=f:color=black` after the last join, where `L` is the planned length. The fades only scale samples/pixels, so the length is unchanged (live: 138.99 s vs 139.02 s planned, same as before). [found]
- Measured on the live outputs: peak −1 dB at 3–2 s before the end, −7 dB over the last 0.5 s, about **−30 dB in the last 50 ms**. `afade`'s default curve is linear (`tri`), so 50 ms before the end the gain is still ~5 %. The offline test therefore checks the last **20 ms** (fixtures: −84 / −50 dB) against −30 dB. [found]
- Video: average luma of the last frame ~**20** (black = 16) vs ~138 without the fade. The last frame starts 1/30 s before the end, so it's not fully black by design; the test threshold is 30. [found]
- The tests were checked against a build with the fade forced to 0: both fade tests then fail (end peak −1.7 / −7.3 dB). [found]
- If the last song is shorter than two crossfades, the fade-out overlaps the join's crossfade. Harmless, just shorter at full volume. [known]

**Row range.** `--rows 2-3`, `--rows 5` (= 5-5); any dash, spaces ignored. Checked in two steps: the form (backwards, header row 1, not a range) before anything runs; the extent after the sheet is read ("outside the sheet: the last song is on row 4"). The last row is the last row **with content**, because the sheet adapter drops fully empty rows; row numbers still match the sheet. Rows outside the range are never looked up. [found]

**Log file.** `workspace/logs/<date>_<time>.log` (`_2`, `_3` … for runs in the same second). Always includes DEBUG (the exact FFmpeg commands), whatever the console shows (maintainer decision). At start, older logs are deleted so the folder never holds more than 5 files, the current run's included. "Newest" is judged by the date/time in the name, not the modified time. Only files named like a log are ever deleted. [found: 7 live runs → 5 logs]

**Cache-clear prompt.** After a successful run, only when both stdin and stdout are a terminal. Enter, anything but `y`/`yes`, Ctrl+C, or closed input = No. Clearing deletes only files named by the cache rule (`<id>_audio.*`, `<id>_v<n>.*`, including leftovers like `.part`, `.f136.mp4`, `.ytdl`), never subfolders or other files, because the operator may point the cache at a shared folder. Limitation: a file the operator named like `my_audio.mp3` matches the rule. [known]
- Not seen live by Claude: its shell isn't a terminal, so the question is (correctly) never asked there.

**Tests.** `python -m unittest` from the repo root ran **0 tests** before: `tests/` had no `__init__.py`, and discovery only enters packages. Added it; `discover -s tests` still works. Shared fakes live in `tests/fakes.py` (not `test_*.py`, so it isn't collected twice). 26 tests, ~18 s.

