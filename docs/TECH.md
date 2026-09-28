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
- **71 songs (`long.csv`), video:** finished, **2868.48 s = planned**; streams: video 2868.467 s (86 054 frames), audio 2868.478 s. **Render stage 634.8 s** (10.6 min). FFmpeg peaks: 12 video chunks 0.67–0.93 GB (42–58 s each), the audio pass 0.59 GB (351 s, in parallel), join + mux 0.05 GB (5.3 s); **highest 0.93 GB** (one pass: 71 songs would need ~38 GB, §14). Chunk joins at 4:05.03, 8:07.37, 12:09.67, 16:12.00, 20:14.33, 24:16.63, 28:18.97, 32:21.30, 36:23.60, 40:25.93, 44:28.27. ⚠ Run with the YouTube look-up replaced (it answered from the cached file's length, rounded up like YouTube), because of the bot check below; everything else was the real pipeline (CSV adapter, FFmpeg, `long_cache`). The fully live 71-song video run is still to do.

**YouTube bot check.** After ~20 live runs and several hundred look-ups in one morning, look-ups failed with `Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies …`. The countdown look-up failed after 2 retries and the run stopped, as designed. Then plain `HTTP Error 429: Too Many Requests`, still after ~15 min. Not caused by this slice's code; not retried further, to let the limit expire. yt-dlp's suggested fix is cookies (`--cookies-from-browser`), which the program doesn't support; if this happens at a real event, that's a maintainer decision (HANDOFF). [found 2026-09-28]

**Tests.** 67 tests (+21). `test_audio_length.py` (20 Opus countdowns keep the planned length, ±0.02 s; the fixture still has its Opus gap), `test_output_naming.py` (fake processor: success, length mismatch, failure after / before writing, `_FAILED_2`, leftover cleanup, locked leftover on Windows), `test_crossfades.py` (the rule, no overlapping fades, short countdown, short song, 3-frame floor), `test_chunks.py` (split maths, cut inside the solo part, one-frame solo part, 3 chunks rendered with the chunk size patched to 2: length, A/V within a frame, progress, temporary files gone).
