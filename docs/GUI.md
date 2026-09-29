# GUI.md — Operator Window

**Status:** built in slice 5 (release 2026.2). This file describes the window as it is; change it here first, then in code. Owned by the maintainer, like SPEC.md. SPEC wins on conflict.

**Design goal:** minimal, but it guides the eye. The operator should always know three things at a glance: _what will happen_ (top), _what is happening_ (middle), and _what to press_ (bottom).

**Ground rules (from SPEC):**

- The GUI talks only to the core; never to yt-dlp or FFmpeg (§5).
- File-only settings never appear here (§7).
- Settings are edited in memory, checked by the core as you leave a field (it may correct a value and show the corrected one), and saved to `config/config.toml` once, when Run is pressed (§7).
- During a run, everything that could change the run is locked, and unlocked again when it ends (§9 stages 1 and 8).
- All text must display Thai correctly, on Windows and Linux.
- Paths are shown and stored as **full paths**, so the relative-path mistake in SPEC §14 can't happen from the GUI.

**Window:** titled **"LARB - Spicy"**. A fixed **minimum** size; below it, nothing shrinks further. Extra height goes only to the log panel; extra width also widens the text fields. **Fixed dark theme** (plain Tkinter doesn't follow the system's light/dark switch without extra work, so one look is kept on purpose).

**Button order:** Windows and Linux put Run on the left; Mac mirrors the bottom row. (Developer switch `LARB_GUI_MAC=1` forces the Mac row, to check it without a Mac.)

**Icons and title bar:** the program has its own Windows identity, so the taskbar shows its icon, not Python's. Two icons in `src/larb/gui/assets/`: `icon_titlebar.ico` (white) is the small icon in the title bar; `icon_taskbar.ico` (accent) is the large icon in the taskbar and Alt+Tab. Linux uses `icon.png`. On Windows 11 the title bar is DARK with white text, overriding the system's accent colour for this window; older Windows keeps its own title bar.

**Keyboard shortcuts:** Ctrl+C / V / X / A work in text fields with **any keyboard language** (e.g. Thai), because they're recognised by the physical key, not the typed character. Ctrl+A selects all, on Linux too. There's no undo (Ctrl+Z) in text fields; Tkinter doesn't provide one, and these short fields don't need it.

## Colours

A standard dark theme (greys) for everything not listed here: backgrounds, text fields, Browse, Open file, Open folder.

|Name|Hex|Used for|
|---|---|---|
|DARK|`#8B0088`|Log filter "All" when not active; one end of the download sweep|
|LIGHT|`#FF80FF`|Background of Est. Length and Clear cache (black text)|
|NEON|`#FF00FF`|Run button; overall progress bar; filter "All" when active; selected radio dot; other end of the download sweep|
|ORANGE|`#FF8800`|Filter "Warnings" when active; WARNING lines in the log|
|RED|`#FF1900`|Filter "Errors" when active; Stop button; ERROR lines in the log; "Stopped: …" label|

Rules:

- **Filter buttons:** active = their colour (All: NEON, Warnings: ORANGE, Errors: RED). Not active = a darker version of the same colour (All uses DARK; Warnings and Errors are ORANGE and RED moved toward black). Text is always white.
- **Hover:** every coloured button gets a slightly darker version of its idle colour.
- **Run** is NEON with white text; **Stop** is RED with white text.
- **Radio buttons:** the selected dot is NEON. The circle is white when the choice is usable, dark grey when it's greyed out.

---

## Layer 1 — Sketch

Windows and Linux layout. On Mac, the bottom row is mirrored. The panes have no titles on screen; the pane names in this file are only for talking about the design.

```
┌──────────────────────────────────────────────────────────────────────┐
│   Sheet     [ Google Sheet link / Path to CSV file          ] [Browse]│
│   Rows      from [    ] to [    ]                                    │
│   Output    (•) Video  ( ) Audio      Mirror  ( ) Everything (•) Ignore│
│   Countdown [ (default countdown)                           ] [Browse]│
│   Crossfade [ 0.8 ] s                                                │
│   Save to   [ D:\larb-spicy\workspace\output                ] [Browse]│
├──────────────────────────────────────────────────────────────────────┤
│   [All] [Warnings (1)] [Errors (0)]                                  │
│   ┌──────────────────────────────────────────────────────────────┐   │
│   │ 23:10:28 INFO     row 2: ok: Perfect Night (27-64 s)         │   │
│   │ 23:10:28 WARNING  row 4: artist is empty                     │   │
│   │ ...                                                          │   │
│   └──────────────────────────────────────────────────────────────┘   │
│   Downloading  [██████████░░░░░░░░░░]  12 / 40                       │
│     Perfect Night - LE SSERAFIM   [ ░▒▓██▓▒░       ]  0:12           │
│     Drama - เอสป้า                [       ░▒▓██▓▒░ ]  0:42           │
│     Ditto                         [   ▓██▓▒░       ]  0:05           │
│                                             [Open file] [Open folder]│
├──────────────────────────────────────────────────────────────────────┤
│   [    RUN    ]                          [Est. Length] [Clear cache] │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Layer 2 — Outline

1. **Top pane — what to make** (ordered by how often it's used)
    1. Sheet link / CSV file
    2. Row range
    3. Output mode + Mirror (one row)
    4. Countdown
    5. Crossfade
    6. Output folder
2. **Middle pane — what's happening**
    1. Log filter
    2. Log panel
    3. Progress (overall bar + active downloads)
    4. Open file / Open folder
3. **Bottom pane — what to press**
    1. Run / Stop
    2. Est. Length (disabled, future)
    3. Clear cache

---

## Layer 3 — Element cards

Card fields: **Kind** · **Maps to** (config key, or run input = not saved) · **Default** · **Checked when** · **During a run** · **Why here**.

### 1.1 Sheet link / CSV file

- **Kind:** one-line text field + Browse button (Browse picks a local CSV).
- **Maps to:** run input.
- **Default:** empty, placeholder "Google Sheet link / Path to CSV file". Not remembered between sessions (see Upgrades).
- **Checked when:** on Run. A private or unreachable sheet, or a missing column header, aborts the run with a pop-up (see "Aborted runs").
- **During a run:** locked.
- **Why here:** used every single run, so it's first.

### 1.2 Row range

- **Kind:** two small number fields, "from [ ] to [ ]".
- **Maps to:** run input (the row range, SPEC §8).
- **Default:** an empty field is an open edge:
    - `from 3, to (empty)` → row 3 to the last row.
    - `from (empty), to 10` → the first song row to row 10.
    - both empty → all rows.
- **Checked when:** on Run. Backwards or outside the sheet → the core's message (§8).
- **During a run:** locked.
- **Why here:** used whenever a long list is done in sections.

### 1.3 Output mode + Mirror (one row)

- **Kind:** two radio groups side by side:
    - **Output:** "Video" / "Audio".
    - **Mirror:** "Everything" / "Ignore". **Greyed out when Audio is selected**, since mirroring only affects the picture.
    - Hover hint on Mirror: "Everything: every song ends up mirrored; rows already marked in the sheet's Mirrored column are not flipped twice. Ignore: nothing is flipped."
- **Maps to:** `processing.audio_only` (Audio = true) and `processing.mirror` (Everything = true, Ignore = false; §8 Mirror rule).
- **Default:** from `config.toml`.
- **Checked when:** — (can't be invalid).
- **During a run:** locked.
- **Why here:** one row because Mirror depends on Output; the biggest choices about the result, so they're near the top.

### 1.4 Countdown

- **Kind:** one-line field that accepts a YouTube link or a file, + Browse button. When empty, shows "(default countdown)".
- **Maps to:** run input (`--countdown`). Empty → the core uses `countdown.default_urls` / `default_files` (§7). **Never changes the default:** defaults are the fallback, this field is for one run. (Remembering the last one used: see Upgrades.)
- **Default:** empty = the default countdown.
- **Checked when:** on Run, before the manifest (§9 stage 3).
- **During a run:** locked.
- **Why here:** usually left alone; below the per-event choices.

### 1.5 Crossfade

- **Kind:** small number field, seconds.
- **Maps to:** `processing.crossfade_duration_seconds`.
- **Default:** **0.8 s**.
- **Checked when:** on leaving the field:
    - Not a number (e.g. "abc", empty) → restored to the default, 0.8.
    - Below 0.1 (including 0 and negatives) → 0.1. Over 10 → 10. The field shows the corrected value.
- **During a run:** locked.
- **Why here:** rarely changed, so it's low in the pane.

### 1.6 Output folder

- **Kind:** one-line field + Browse button. Shows the full path.
- **Maps to:** `output.directory`.
- **Default:** empty = `workspace/output/`, shown as its full path.
- **Checked when:** on Run. A folder that doesn't exist is **created**. If creating it fails (e.g. no permission), refuse with a message naming the folder, before anything is downloaded.
- **During a run:** locked.
- **Why here:** set once per machine, so it's last.

### 2.1 Log filter

- **Kind:** three small toggle buttons at the log's top left: "All" / "Warnings (n)" / "Errors (n)", with live counts. "Warnings" shows warnings and errors. The warning count includes the end-of-run cache reminder and the "stopped by the operator" line.
- **Maps to:** display only.
- **Default:** All.
- **During a run:** usable; filtering never pauses or changes the run.
- **Why here:** lets the operator find the one problem in a 300-song log; the counts double as the run's summary.

### 2.2 Log panel

- **Kind:** read-only, scrolling text area. The biggest part of the window, and the only part that grows with the window.
- **Maps to:** the core's log events (the `EventSink` port).
- **Colours** (on the dark theme):
    - INFO: light grey text.
    - WARNING: ORANGE.
    - ERROR: RED, bold.
    - Stage names (`sheet`, `manifest`, `download`, `render`): muted grey, so the message stands out.
    - DEBUG: never shown here; it's in the log file (§11).
- **Scrolling:** follows new lines automatically, but stops following while the operator has scrolled up to read, and resumes when they scroll back to the bottom.
- **During a run:** live.
- **Why here:** the centre of attention while a run is going.

### 2.3 Progress

- **Kind:** two parts, shown only while a run is going:
    - **Overall bar:** stage name + "done / total", and the label follows the run from stage to stage: "Starting" → "Reading the sheet" → "Preparing the countdown" → "Checking 12 / 40" → "Downloading 12 / 40" → "Measuring 12 / 40" → "Rendering part 3 / 7" (audio: just "Rendering", since it's one pass). Real progress. When the run ends, the same label shows how it ended: "Finished", "Stopping..." then "Stopped: you pressed Stop", or in RED, "Stopped: <reason>" (long reasons wrap). This replaces a separate result line.
    - **Active downloads:** one row per download in progress (up to `max_parallel_downloads`, e.g. 3): song title, a sweeping "busy" animation (a drawn gradient bar, since Tkinter's own indeterminate bar can't show a gradient), and how long it has been downloading (e.g. `0:42`). When a song finishes, its row disappears and the next song takes its place.
- **Maps to:** overall bar: the core's `LogEvent.progress`. Active downloads: the core's "download started" / "download finished" events for each row, as **structured data, never parsed from log text**. Not shown in the log panel, so the filter stays clean.
- **Why the timer:** the animation only shows the program is alive; the timer shows a stuck download (normal songs finish in well under a minute).
- **Colours:** overall bar: NEON on the theme's bar background. Active downloads: a sweeping gradient between DARK and NEON on the theme's bar background.
- **During a run:** live.
- **Why here:** the operator sees movement at all times, without reading the log.

### 2.4 Open file / Open folder

- **Kind:** two small buttons, bottom right of the middle pane.
- **Maps to:** the finished output file and its folder, opened with the system's default app / file manager.
- **Enabled:** only after a successful run; disabled otherwise.
- **Why here:** right under the progress label that says "Finished".

### 3.1 Run / Stop

- **Kind:** the largest button, bold, NEON with white text. **Left** on Windows and Linux, **right** on Mac.
- **Maps to:** Run: validate all settings, save them to `config.toml`, lock the top pane, run the pipeline (§9).
- **During a run:** the same button becomes **Stop** (RED, white text). Pressing it asks "Stop the run?" [Stop] [Keep running], with Keep running as the default, since one misclick would otherwise end a long run.
    - After stopping: anything already rendered follows the rule "nothing unverified gets the final name" (it becomes `_FAILED`); songs already downloaded stay cached; interrupted downloads are cleaned up.
- **After a run:** everything unlocks.
- **Why here:** the first thing the eye lands on in the bottom row.

### 3.2 Est. Length

- **Kind:** LIGHT background, black text, **always disabled** for now (shown greyed), with the hover hint "Coming later".
- **Why here:** reminds the operator and successors that it's planned (HANDOFF upgrade list), without taking effort now.

### 3.3 Clear cache

- **Kind:** LIGHT background, black text, at the far end of the bottom row (right on Windows and Linux, left on Mac).
- **Maps to:** the core's cache clearing (§10: only cache-named files).
- **Checked when:** on click: a confirmation, "Delete N downloaded files (X MB)? [Delete] [Cancel]", with Cancel as the default. An empty cache just says "The cache is empty".
- **During a run:** disabled.
- **Why here:** far from Run, so it's never pressed by accident.
- **After each run:** no question is asked. Instead, a WARNING line at the end of the log reminds the operator: "The cache holds N files (X GB). Use Clear cache when you're done."

---

## Dialogs

- **Aborted runs** (private sheet, missing header, bad row range, no countdown, output folder can't be created, or any unexpected error): a **blocking pop-up** with the core's message. An operator's own Stop shows no pop-up. The main window can't be used until it's closed. The progress label also shows "Stopped: <reason>".
- **Closing with unsaved edits:** ask "Save your changes?" [Save] [Don't save] [Cancel].
- **Closing during a run:** ask "A run is in progress. Stop it and close?" [Stop and close] [Keep running], with Keep running as the default.

---

## How it's built

Built in slice 5; details and quirks in TECH.md §18–19.

- The window never calls yt-dlp or FFmpeg; `src/larb/app.py` builds the pipeline for both the window and the terminal version.
- The run happens on a background thread; only the window's own thread touches widgets.
- Stop uses the ports' `cancel()` methods; active-download rows come from structured "started / ended" events, never from log text.
- Every decision the window makes (what's enabled, what the progress label says, field corrections) lives in `src/larb/gui/state.py`, so it's tested without opening a window.