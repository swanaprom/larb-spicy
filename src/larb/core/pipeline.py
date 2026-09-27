"""The pipeline: runs the stages of SPEC §9 in order, talking to the world only through ports."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from larb.core.cache import cache_stem, find_cached
from larb.core.errors import (DownloadError, LarbError, MediaUnavailableError, RenderError)
from larb.core.manifest import ParsedRow, RowProblem, parse_row, select_rows
from larb.core.models import (DownloadSettings, Level, LogEvent, ManifestEntry, MediaKind, RenderPlan,
                              RowRange, RunResult, Segment, Settings)
from larb.core.ports import EventSink, MediaProcessor, MediaSource, SongListSource
from larb.core.settings import validate_settings

PADDING_S = 1.0             # each song starts 1 s early and ends 1 s late (SPEC §4 "Padding")
TARGET_PEAK_DB = -1.0       # peak normalization target, hard-coded (SPEC §7, §9)
SILENT_PEAK_DB = -60.0      # below this a clip is treated as silent: no gain, warn instead
OVERRUN_TRIM_LIMIT_S = 1.0  # end past the real length by up to this -> trim to fit (SPEC §9 stage 6)
LENGTH_TOLERANCE_S = 0.1    # allowed difference between planned and actual output length
RETRY_PAUSE_S = 1.0         # pause before retry n is n * this

# Characters Windows doesn't allow in file names.
_ILLEGAL_FILENAME_CHARS = set('<>:"/\\|?*')


def is_url(text: str) -> bool:
    """True for a web address (countdown or sheet), False for a local file path."""
    return text.strip().lower().startswith(("http://", "https://"))


def choose_countdown(given: str | None, settings: Settings) -> str:
    """The countdown to use: the one given for this run, else the first of
    countdown.default_urls, else the first of countdown.default_files.

    Returns:
        A URL or a local file path (see is_url).

    Raises:
        LarbError: No countdown given and none set in the settings.
    """
    for candidate in (given, *settings.countdown.default_urls, *settings.countdown.default_files):
        if candidate and candidate.strip():
            return candidate.strip()
    raise LarbError("No countdown. Pass --countdown with a file or a YouTube URL, or set "
                    "countdown.default_urls or countdown.default_files in the settings file")


class Pipeline:
    """One run of the whole compilation.

    Args:
        workspace: Where runtime files go. Default cache and output folders live
            here, and relative folder settings are resolved against it.
    """

    def __init__(self, songs: SongListSource, media: MediaSource, processor: MediaProcessor,
                 events: EventSink, workspace: Path) -> None:
        self._songs = songs
        self._media = media
        self._processor = processor
        self._events = events
        self._workspace = workspace
        self._counts_lock = threading.Lock()
        self._errors = 0
        self._warnings = 0

    # -- logging helpers ---------------------------------------------------

    def _log(self, level: Level, stage: str, message: str, row: int | None = None) -> None:
        if level is Level.ERROR and row is not None:
            with self._counts_lock:
                self._errors += 1
        elif level is Level.WARNING and row is not None:
            with self._counts_lock:
                self._warnings += 1
        self._events.emit(LogEvent(level, stage, message, row))

    # -- the run -----------------------------------------------------------

    def run(self, source: str, countdown: str, settings: Settings,
            now: datetime | None = None, rows: RowRange | None = None) -> RunResult:
        """Run every stage and return where the output went.

        Row problems are logged and the row is skipped; the rest still renders.
        Problems that make the whole run impossible raise.

        Args:
            source: Where the song list is (sheet URL or CSV file).
            countdown: A countdown URL or local file path (see choose_countdown).
            rows: Only use these sheet rows. None = all rows.

        Raises:
            LarbError: The run can't produce an output (no songs left, sheet
                unreadable, FFmpeg missing, render failed, ...).
        """
        now = now or datetime.now()
        # Stage 1: lock settings. `settings` is frozen and used as-is for the whole run;
        # changes made elsewhere during the run are not picked up (SPEC §5).
        validate_settings(settings)
        kind = MediaKind(settings.processing.audio_only, settings.download.max_height)
        cache_dir = self._resolve_dir(settings.download.cache_directory, "cache")
        output_dir = self._resolve_dir(settings.output.directory, "output")
        self._log(Level.INFO, "settings", f"Mode: {'audio only' if kind.audio_only else f'video up to {kind.max_height}p'}, "
                  f"mirror: {'on' if settings.processing.mirror else 'off'}. Media tool: {self._processor.describe()}")

        # Stage 2: fetch the song list.
        self._log(Level.INFO, "sheet", f"Reading song list: {source}")
        sheet_rows = self._songs.fetch_rows(source)
        self._log(Level.INFO, "sheet", f"{len(sheet_rows)} row(s) found")
        if rows is not None:
            sheet_rows = select_rows(sheet_rows, rows)
            self._log(Level.INFO, "sheet", f"Using rows {rows.first}-{rows.last}: "
                      f"{len(sheet_rows)} row(s) with content")

        # Stage 4, done before stage 3 on purpose: a run can't succeed without the
        # countdown, so a bad one should stop it before minutes of manifest look-ups.
        countdown_segment = self._prepare_countdown(countdown, kind, cache_dir, settings)

        # Stage 3: build the manifest (offline rules, then ask the media source).
        entries = self._build_manifest(sheet_rows)

        # Stage 5: download songs (cached ones are skipped).
        paths = self._download_all(entries, kind, cache_dir, settings.download)

        # Stage 6: check real lengths and measure peaks.
        segments = self._measure_songs(entries, paths, settings)
        if not segments:
            raise LarbError("No usable songs left, nothing to render. See the errors above.")

        # Stage 7: render in one pass.
        plan_segments = []
        for song in segments:
            plan_segments += [countdown_segment, song]
        crossfade = settings.processing.crossfade_duration_seconds
        # The end fade-out is as long as a crossfade: hard-coded, not a setting (SPEC §9 stage 7).
        plan = RenderPlan(tuple(plan_segments), crossfade, kind.audio_only, kind.max_height,
                          fade_out_s=crossfade)
        output = self._output_path(output_dir, settings.output.filename_template, kind, now)
        self._log(Level.INFO, "render", f"Rendering {len(segments)} song(s), "
                  f"about {plan.expected_duration_s:.1f} s long -> {output}")
        started = time.perf_counter()
        self._processor.render(plan, output)
        self._verify_output(output, plan)
        self._log(Level.INFO, "render", f"Done in {time.perf_counter() - started:.1f} s: {output}")

        # Stage 8 (unlock the GUI) belongs to the GUI; nothing to do here.
        return RunResult(output, len(segments), self._errors, self._warnings, cache_dir)

    # -- stage helpers ---------------------------------------------------------

    def _resolve_dir(self, setting: str, default_name: str) -> Path:
        path = Path(setting) if setting else Path(default_name)
        if not path.is_absolute():
            path = self._workspace / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _build_manifest(self, rows) -> list[ManifestEntry]:
        entries = []
        for row in rows:
            try:
                parsed: ParsedRow = parse_row(row.row_number, row.song_title, row.artist,
                                              row.url, row.time_range, row.mirrored)
            except RowProblem as problem:
                self._log(Level.ERROR, "manifest", f"skipped: {problem}", row.row_number)
                continue
            for warning in parsed.warnings:
                self._log(Level.WARNING, "manifest", warning, row.row_number)
            try:
                info = self._media.lookup(parsed.url)
            except MediaUnavailableError as e:
                self._log(Level.ERROR, "manifest", f"skipped: video unavailable: {e}", row.row_number)
                continue
            # YouTube rounds the length to whole seconds, so this catches most bad
            # ranges before downloading; stage 6 checks the real file again.
            if parsed.end_s > info.duration_s:
                self._log(Level.ERROR, "manifest", f"skipped: end time {parsed.end_s} s is past the "
                          f"video's length ({info.duration_s:.0f} s)", row.row_number)
                continue
            entry = ManifestEntry(parsed.row_number, parsed.title, parsed.artist, parsed.url,
                                  float(parsed.start_s), float(parsed.end_s), parsed.already_mirrored, info)
            self._log(Level.INFO, "manifest", f"ok: {entry.display_name} "
                      f"({parsed.start_s}-{parsed.end_s} s{', already mirrored' if parsed.already_mirrored else ''})",
                      row.row_number)
            entries.append(entry)
        self._log(Level.INFO, "manifest", f"{len(entries)} of {len(rows)} row(s) usable")
        return entries

    def _prepare_countdown(self, countdown: str, kind: MediaKind, cache_dir: Path,
                           settings: Settings) -> Segment:
        """Get the countdown (downloading it if it's a URL) and measure it.

        Raises:
            LarbError: The countdown can't be found, downloaded or used. The run stops:
                there is no compilation without a countdown.
        """
        if is_url(countdown):
            path = self._fetch_countdown(countdown.strip(), kind, cache_dir, settings.download)
        else:
            path = Path(countdown)
            if not path.is_file():
                raise LarbError(f"Countdown file not found: {path}")
        return self._check_countdown(path, settings.processing.crossfade_duration_seconds)

    def _fetch_countdown(self, url: str, kind: MediaKind, cache_dir: Path, dl: DownloadSettings) -> Path:
        """A countdown URL goes through the media source like a song: same look-up,
        same cache name, same retries. Only the failure differs: it stops the run."""
        try:
            info = self._media.lookup(url)
        except MediaUnavailableError as e:
            raise LarbError(f"Countdown video unavailable: {e}") from None
        name = f"countdown {info.title or url}"
        stem = cache_stem(info.media_id, kind)
        cached = find_cached(cache_dir, stem)
        if cached:
            self._log(Level.INFO, "countdown", f"cached: {name} ({cached.name})")
            return cached
        self._log(Level.INFO, "countdown", f"Downloading {name}")
        try:
            return self._download_with_retries(url, stem, name, None, kind, cache_dir, dl.max_retries)
        except DownloadError as e:
            raise LarbError(f"Countdown download failed: {e}") from None

    def _check_countdown(self, path: Path, crossfade_s: float) -> Segment:
        info = self._processor.measure(path, 0.0, None)
        if info.duration_s <= crossfade_s:
            raise LarbError(f"Countdown is {info.duration_s:.2f} s long, which is not longer "
                            f"than the crossfade ({crossfade_s} s)")
        gain = self._gain_for(info.peak_db, "countdown", None)
        self._log(Level.INFO, "countdown", f"{path.name}: {info.duration_s:.2f} s, gain {gain:+.1f} dB")
        return Segment(path, 0.0, info.duration_s, mirror=False, gain_db=gain)  # countdowns never mirror

    def _download_all(self, entries, kind: MediaKind, cache_dir: Path, dl) -> dict[str, Path]:
        """Download each distinct video once. Returns media_id -> file for the ones that worked."""
        by_id: dict[str, ManifestEntry] = {}
        for entry in entries:
            by_id.setdefault(entry.media.media_id, entry)   # same video twice = one download
        paths: dict[str, Path] = {}
        todo = []
        for media_id, entry in by_id.items():
            cached = find_cached(cache_dir, cache_stem(media_id, kind))
            if cached:
                self._log(Level.INFO, "download", f"cached: {entry.display_name} ({cached.name})", entry.row_number)
                paths[media_id] = cached
            else:
                todo.append(entry)
        if todo:
            self._log(Level.INFO, "download", f"Downloading {len(todo)} video(s), "
                      f"up to {dl.max_parallel_downloads} at once")
            with ThreadPoolExecutor(max_workers=dl.max_parallel_downloads) as pool:
                results = pool.map(lambda e: (e, self._download_one(e, kind, cache_dir, dl.max_retries)), todo)
                for entry, path in results:
                    if path:
                        paths[entry.media.media_id] = path
        return paths

    def _download_one(self, entry: ManifestEntry, kind: MediaKind, cache_dir: Path,
                      max_retries: int) -> Path | None:
        """One song. Runs in a worker thread. A failure becomes a row error."""
        stem = cache_stem(entry.media.media_id, kind)
        try:
            return self._download_with_retries(entry.url, stem, entry.display_name, entry.row_number,
                                               kind, cache_dir, max_retries)
        except DownloadError as e:
            self._log(Level.ERROR, "download", f"skipped: {entry.display_name}: {e}", entry.row_number)
            return None

    def _download_with_retries(self, url: str, stem: str, name: str, row: int | None,
                               kind: MediaKind, cache_dir: Path, max_retries: int) -> Path:
        """Download one video (song or countdown), retrying retryable errors up to max_retries times.

        Raises:
            DownloadError: The last try failed, or the error isn't worth retrying.
        """
        for attempt in range(max_retries + 1):
            try:
                path = self._media.download(url, kind, cache_dir, stem)
                self._log(Level.INFO, "download", f"done: {name} ({path.name})", row)
                return path
            except DownloadError as e:
                if attempt == max_retries or not e.retryable:
                    raise
                self._log(Level.WARNING, "download", f"retry {attempt + 1}/{max_retries}: {name}: {e}", row)
                time.sleep(RETRY_PAUSE_S * (attempt + 1))
        raise AssertionError("unreachable: the loop always returns or raises")

    def _measure_songs(self, entries, paths: dict[str, Path], settings: Settings) -> list[Segment]:
        crossfade = settings.processing.crossfade_duration_seconds
        segments = []
        for entry in entries:
            path = paths.get(entry.media.media_id)
            if path is None:
                continue  # download failed, already reported
            try:
                info = self._processor.measure(path, max(0.0, entry.start_s - PADDING_S),
                                               entry.end_s + PADDING_S)
            except RenderError as e:
                self._log(Level.ERROR, "measure", f"skipped: can't read {path.name}: {e}", entry.row_number)
                continue
            real, start, end = info.duration_s, entry.start_s, entry.end_s
            if start >= real:
                self._log(Level.ERROR, "measure", f"skipped: start {start:.0f} s is past the "
                          f"song's real length ({real:.2f} s)", entry.row_number)
                continue
            if end > real:
                over = end - real
                if over > OVERRUN_TRIM_LIMIT_S:
                    self._log(Level.ERROR, "measure", f"skipped: end {end:.0f} s is {over:.2f} s past "
                              f"the song's real length ({real:.2f} s)", entry.row_number)
                    continue
                self._log(Level.WARNING, "measure", f"end {end:.0f} s is {over:.2f} s past the real "
                          f"length ({real:.2f} s); trimmed to fit", entry.row_number)
                end = real
            # Padding, clamped to the file (SPEC §4).
            start, end = max(0.0, start - PADDING_S), min(real, end + PADDING_S)
            if end - start <= crossfade:
                self._log(Level.ERROR, "measure", f"skipped: clip is {end - start:.2f} s, "
                          f"not longer than the crossfade ({crossfade} s)", entry.row_number)
                continue
            mirror = settings.processing.mirror and not entry.already_mirrored  # SPEC §8 Mirror rule
            gain = self._gain_for(info.peak_db, "measure", entry.row_number)
            segments.append(Segment(path, start, end, mirror, gain))
            self._log(Level.DEBUG, "measure", f"{entry.display_name}: {start:.1f}-{end:.1f} s, "
                      f"peak {info.peak_db:.1f} dB -> gain {gain:+.1f} dB, mirror {mirror}", entry.row_number)
        return segments

    def _gain_for(self, peak_db: float, stage: str, row: int | None) -> float:
        """Peak normalization: bring the clip's loudest point to TARGET_PEAK_DB."""
        if peak_db <= SILENT_PEAK_DB:
            self._log(Level.WARNING, stage, f"clip is (nearly) silent (peak {peak_db:.1f} dB); "
                      "left at its original volume", row)
            return 0.0
        return TARGET_PEAK_DB - peak_db

    def _output_path(self, output_dir: Path, template: str, kind: MediaKind, now: datetime) -> Path:
        template = template or "{date}_{time}"
        try:
            # No ":" in the time: it's illegal in Windows file names (TECH §7).
            name = template.format(date=now.strftime("%Y-%m-%d"), time=now.strftime("%H%M%S"))
        except (KeyError, IndexError, ValueError) as e:
            raise LarbError(f"output.filename_template {template!r} is invalid: only {{date}} and "
                            f"{{time}} can be used ({e})") from None
        bad = _ILLEGAL_FILENAME_CHARS & set(name)
        if bad or not name.strip():
            raise LarbError(f"output.filename_template gives an unusable file name {name!r}")
        ext = ".mp3" if kind.audio_only else ".mp4"   # hard-coded output formats (SPEC §7)
        path = output_dir / f"{name}{ext}"
        n = 2
        while path.exists():  # never overwrite an earlier output
            path = output_dir / f"{name}_{n}{ext}"
            n += 1
        return path

    def _verify_output(self, output: Path, plan: RenderPlan) -> None:
        """Goal 1: FFmpeg can succeed and still write a wrong file, so check the length."""
        if not output.is_file():
            raise RenderError(f"The renderer reported success but {output} doesn't exist")
        # A tiny peak range keeps this fast; only the real length matters here.
        actual = self._processor.measure(output, 0.0, 0.1).duration_s
        expected = plan.expected_duration_s
        if abs(actual - expected) > LENGTH_TOLERANCE_S:
            raise RenderError(f"Output is {actual:.2f} s long but should be {expected:.2f} s: {output}")
        self._log(Level.INFO, "render", f"Length check ok: {actual:.2f} s (planned {expected:.2f} s)")
