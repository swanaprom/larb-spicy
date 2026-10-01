"""The pipeline: runs the stages of SPEC §9 in order, talking to the world only through ports."""

import random
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from larb.core.cache import cache_stem, find_cached, remove_leftovers
from larb.core.errors import (DownloadError, LarbError, MediaUnavailableError, RateLimitedError,
                              RenderError, StoppedError)
from larb.core.manifest import ParsedRow, RowProblem, parse_row, select_rows
from larb.core.models import (Activity, ClipInfo, DownloadSettings, Level, LogEvent, ManifestEntry,
                              MediaInfo, MediaKind, RenderPlan, RowRange, RunResult, Segment, Settings,
                              SheetRow)
from larb.core.ports import EventSink, MediaProcessor, MediaSource, SongListSource
from larb.core.settings import ensure_folder, resolve_folder, validate_settings

PADDING_S = 1.0             # each song starts 1 s early and ends 1 s late (SPEC §4 "Padding")
TARGET_PEAK_DB = -1.0       # peak normalization target, hard-coded (SPEC §7, §9)
SILENT_PEAK_DB = -60.0      # below this a clip is treated as silent: no gain, warn instead
OVERRUN_TRIM_LIMIT_S = 1.0  # end past the real length by up to this -> trim to fit (SPEC §9 stage 6)
LENGTH_TOLERANCE_S = 0.1    # allowed difference between planned and actual output length
# Retry waits: RETRY_BASE_S, then twice that, four times ..., each varied by up to
# RETRY_JITTER either way, so retries from parallel workers don't arrive together
# (SPEC §9 stage 5). Values: TECH §20.
RETRY_BASE_S = 2.0
RETRY_JITTER = 0.25
SHORT_STREAM_WARN_S = 0.5   # a clip's video or audio this much shorter than the clip -> warn
FRAME_S = 1 / 30           # one frame of the output (30 fps is the hard-coded format, SPEC §7)
MIN_CLIP_S = 3 * FRAME_S    # shorter clips can't hold a crossfade of even one frame on both sides
RENDERING_SUFFIX = ".rendering"   # <name>.rendering.<ext>: output not checked yet
FAILED_SUFFIX = "_FAILED"         # <name>_FAILED.<ext>: output rejected by the checks
STOPPED_MESSAGE = "Stopped by the operator"
RATE_LIMITED_MESSAGE = ("YouTube is limiting this connection. Wait a while, then run again; "
                        "finished songs stay cached.")

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


def retry_wait_s(attempt: int, rng: random.Random) -> float:
    """How long to wait before retry number attempt + 1 (attempt 0 = the first retry):
    RETRY_BASE_S x 2^attempt, varied by up to RETRY_JITTER either way."""
    return RETRY_BASE_S * 2 ** attempt * rng.uniform(1 - RETRY_JITTER, 1 + RETRY_JITTER)


def crossfade_limits(durations: list[float], fade_out: bool) -> list[float]:
    """The longest crossfade each clip can hold without its fades overlapping.

    A clip keeps at least one frame to itself: its length minus one frame, halved
    when it has a fade on both sides (a crossfade in and out, or in and the end
    fade-out). That also leaves room to cut the video inside every countdown.

    Args:
        durations: The clips' lengths, in playing order.
        fade_out: Whether the last clip also has the end fade-out.
    """
    n, limits = len(durations), []
    for i, length in enumerate(durations):
        sides = (i > 0) + (i < n - 1) + (i == n - 1 and fade_out)
        limits.append((length - FRAME_S) / (2 if sides >= 2 else 1))
    return limits


def plan_crossfades(durations: list[float], setting_s: float) -> tuple[tuple[float, ...], float]:
    """Each join's crossfade, and the end fade-out: the setting, or the longest both
    clips next to it can hold (crossfade_limits), whichever is smaller.

    Returns:
        (one crossfade per join, the end fade-out length)
    """
    limits = crossfade_limits(durations, fade_out=True)
    joins = tuple(min(setting_s, limits[i], limits[i + 1]) for i in range(len(durations) - 1))
    return joins, min(setting_s, limits[-1])


@dataclass
class _RowCheck:
    """The outcome of checking one sheet row, kept until it's this row's turn to be
    reported (rows are checked in parallel but reported in sheet order)."""

    row_number: int
    entry: ManifestEntry | None = None
    messages: list[tuple[Level, str]] = field(default_factory=list)
    from_cache: bool = False   # checked from the cached file, not looked up


class Pipeline:
    """One run of the whole compilation.

    Can be stopped from another thread with stop(). One Pipeline is one run.

    Args:
        workspace: Where runtime files go. Default cache and output folders live here.
        project_dir: The project folder; relative folder settings start here
            (settings.resolve_folder). Default: the folder holding `workspace`.
        rng: Randomness for the retry waits (retry_wait_s). Tests pass a seeded one.
        wait: wait(seconds) waits before a retry and returns True if the run was
            stopped meanwhile. Default: a wait that a stop ends at once. Tests pass
            one that records the waits instead of waiting.
    """

    def __init__(self, songs: SongListSource, media: MediaSource, processor: MediaProcessor,
                 events: EventSink, workspace: Path, project_dir: Path | None = None,
                 rng: random.Random | None = None, wait: Callable[[float], bool] | None = None) -> None:
        self._songs = songs
        self._media = media
        self._processor = processor
        self._events = events
        self._workspace = workspace
        self._project_dir = project_dir or workspace.parent
        self._counts_lock = threading.Lock()
        self._errors = 0
        self._warnings = 0
        self._stop = threading.Event()
        self._rng = rng or random.Random()
        self._wait = wait or self._stop.wait
        # Set when the media source limits the connection: no new look-ups or downloads
        # start, running ones end, then the run stops (SPEC §9 stage 5).
        self._limited = threading.Event()

    # -- stopping ----------------------------------------------------------

    def stop(self) -> None:
        """Ask the run to stop (SPEC §9 "Stopped by the operator"). Returns at once;
        run() then raises StoppedError as soon as it can. Safe from any thread.

        A look-up already running finishes first; downloads and FFmpeg stop. The
        outcome is the same as any failed run: nothing unverified gets the final
        output name, finished downloads stay cached, interrupted ones are removed.
        """
        self._stop.set()
        self._media.cancel()
        self._processor.cancel()

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise StoppedError(STOPPED_MESSAGE)

    def _pause(self, seconds: float) -> None:
        """Wait before a retry; a stop ends the wait at once."""
        if self._wait(seconds) or self._stop.is_set():
            raise StoppedError(STOPPED_MESSAGE)

    # -- rate limit ----------------------------------------------------------

    def _halted(self) -> bool:
        """True when no new look-up or download should start: stopped, or rate limited."""
        return self._stop.is_set() or self._limited.is_set()

    def _note_rate_limit(self, stage: str, error: RateLimitedError) -> None:
        """Remember the rate limit. The first message is logged as it came; later ones add nothing."""
        if not self._limited.is_set():
            self._limited.set()
            self._log(Level.WARNING, stage, f"YouTube is limiting this connection ({error}). "
                      "Starting nothing new; letting running work finish.")

    def _check_rate_limit(self, rows: list[SheetRow], kind: MediaKind, cache_dir: Path) -> None:
        """End a rate-limited run, saying how much is cached, so the operator knows the
        rerun will be quick (SPEC §9 stage 5)."""
        if not self._limited.is_set():
            return
        cached = sum(1 for row in rows if self._cached_file(row.url, kind, cache_dir))
        raise RateLimitedError(f"{RATE_LIMITED_MESSAGE}\n{cached} of {len(rows)} song(s) are downloaded "
                               "and cached; the next run won't download or look them up again.")

    def _cached_file(self, url: str, kind: MediaKind, cache_dir: Path) -> Path | None:
        """The cached file for this URL and mode, found without asking the media source."""
        media_id = self._media.media_id(url.strip()) if url.strip() else None
        return find_cached(cache_dir, cache_stem(media_id, kind)) if media_id else None

    # -- logging helpers ---------------------------------------------------

    def _log(self, level: Level, stage: str, message: str, row: int | None = None,
             progress: tuple[int, int] | None = None) -> None:
        if level is Level.ERROR and row is not None:
            with self._counts_lock:
                self._errors += 1
        elif level is Level.WARNING and row is not None:
            with self._counts_lock:
                self._warnings += 1
        self._events.emit(LogEvent(level, stage, message, row, progress))

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
            StoppedError: stop() was called.
            LarbError: The run can't produce an output (no songs left, sheet
                unreadable, FFmpeg missing, render failed, ...).
        """
        try:
            return self._run(source, countdown, settings, now or datetime.now(), rows)
        except StoppedError:
            # Adapters say only "Stopped"; one message for every way a stop ends a run.
            raise StoppedError(STOPPED_MESSAGE) from None

    def _run(self, source: str, countdown: str, settings: Settings, now: datetime,
             rows: RowRange | None) -> RunResult:
        # Stage 1: lock settings. `settings` is frozen and used as-is for the whole run;
        # changes made elsewhere during the run are not picked up (SPEC §5).
        validate_settings(settings)
        kind = MediaKind(settings.processing.audio_only, settings.download.max_height)
        # Folders first, so one that can't be created stops the run before any download.
        cache_dir = ensure_folder(resolve_folder(settings.download.cache_directory, "cache",
                                                 self._project_dir, self._workspace), "cache")
        output_dir = ensure_folder(resolve_folder(settings.output.directory, "output",
                                                  self._project_dir, self._workspace), "output")
        self._remove_leftover_renders(output_dir)
        self._log(Level.INFO, "settings", f"Mode: {'audio only' if kind.audio_only else f'video up to {kind.max_height}p'}, "
                  f"mirror: {'on' if settings.processing.mirror else 'off'}. Media tool: {self._processor.describe()}")

        # Stage 2: fetch the song list.
        self._log(Level.INFO, "sheet", f"Reading song list: {source}")
        sheet_rows = self._songs.fetch_rows(source)
        self._check_stop()
        self._log(Level.INFO, "sheet", f"{len(sheet_rows)} row(s) found")
        if rows is not None:
            sheet_rows = select_rows(sheet_rows, rows)
            self._log(Level.INFO, "sheet", f"Using rows {rows.describe()}: "
                      f"{len(sheet_rows)} row(s) with content")

        # Stage 3: prepare the countdown before the manifest on purpose: a run can't succeed
        # without it, so a bad one should stop the run before minutes of manifest look-ups.
        try:
            countdown_segment = self._prepare_countdown(countdown, kind, cache_dir, settings)
        except RateLimitedError as e:
            self._note_rate_limit("countdown", e)
        self._check_stop()
        self._check_rate_limit(sheet_rows, kind, cache_dir)

        # Stage 4: build the manifest (offline rules and cached files, then ask the media source).
        entries = self._build_manifest(sheet_rows, settings.download, kind, cache_dir)
        self._check_stop()
        self._check_rate_limit(sheet_rows, kind, cache_dir)

        # Stage 5: download songs (cached ones are skipped).
        paths = self._download_all(entries, kind, cache_dir, settings.download)
        self._check_stop()
        self._check_rate_limit(sheet_rows, kind, cache_dir)

        # Stage 6: check real lengths and measure peaks.
        songs = self._measure_songs(entries, paths, settings, kind)
        if not songs:
            raise LarbError("No usable songs left, nothing to render. See the errors above.")

        # Stage 7: render.
        self._check_stop()
        plan = self._build_plan(countdown_segment, songs, settings.processing.crossfade_duration_seconds, kind)
        output = self._output_path(output_dir, settings.output.filename_template, kind, now)
        self._log(Level.INFO, "render", f"Rendering {len(songs)} song(s), "
                  f"about {plan.expected_duration_s:.1f} s long -> {output}")
        started = time.perf_counter()
        output = self._render_checked(plan, output)
        self._log(Level.INFO, "render", f"Done in {time.perf_counter() - started:.1f} s: {output}")

        # Stage 8 (unlock the GUI) belongs to the GUI; nothing to do here.
        return RunResult(output, len(songs), self._errors, self._warnings, cache_dir)

    # -- stage helpers ---------------------------------------------------------

    def _build_manifest(self, rows: list[SheetRow], dl: DownloadSettings, kind: MediaKind,
                        cache_dir: Path) -> list[ManifestEntry]:
        """Check every row, looking videos up max_parallel_lookups at a time. A row whose
        file for this mode is already cached is checked from that file instead, without
        asking the media source (SPEC §9 stage 4).

        Rows finish in any order, but their results, errors and warnings are
        reported in sheet order. A progress event goes out as each row finishes.
        """
        total = len(rows)
        self._log(Level.INFO, "manifest", f"Checking {total} row(s), "
                  f"up to {dl.max_parallel_lookups} at once", progress=(0, total))
        done = 0
        done_lock = threading.Lock()

        def check(row: SheetRow) -> _RowCheck:
            nonlocal done
            if self._halted():   # rows still waiting are never looked up
                return _RowCheck(row.row_number)
            result = self._check_row(row, dl.max_retries, kind, cache_dir)
            with done_lock:   # also keeps the progress events in counting order
                done += 1
                self._log(Level.INFO, "manifest", f"checked {done}/{total}", row.row_number,
                          progress=(done, total))
            return result

        entries, from_cache = [], 0
        with ThreadPoolExecutor(max_workers=dl.max_parallel_lookups) as pool:
            # map() hands the results back in the order of `rows`, however they finish.
            for result in pool.map(check, rows):
                for level, message in result.messages:
                    self._log(level, "manifest", message, result.row_number)
                if result.entry:
                    entries.append(result.entry)
                    from_cache += result.from_cache
        self._log(Level.INFO, "manifest", f"{len(entries)} of {total} row(s) usable: {from_cache} "
                  f"checked from the cache, {len(entries) - from_cache} looked up")
        return entries

    def _check_row(self, row: SheetRow, max_retries: int, kind: MediaKind, cache_dir: Path) -> _RowCheck:
        """Check one row: offline rules, then the cached file or the media source. Runs in
        a worker thread, so it logs nothing itself; its messages are reported later, in
        sheet order."""
        result = _RowCheck(row.row_number)
        try:
            parsed: ParsedRow = parse_row(row.row_number, row.song_title, row.artist,
                                          row.url, row.time_range, row.mirrored)
        except RowProblem as problem:
            result.messages.append((Level.ERROR, f"skipped: {problem}"))
            return result
        result.messages += [(Level.WARNING, warning) for warning in parsed.warnings]
        cached = self._cached_file(parsed.url, kind, cache_dir)
        if cached:
            return self._check_cached_row(parsed, cached, result)
        try:
            info = self._lookup_with_retries(
                parsed.url, max_retries, lambda msg: result.messages.append((Level.WARNING, msg)))
        except MediaUnavailableError as e:
            result.messages.append((Level.ERROR, f"skipped: video unavailable: {e}"))
            return result
        except RateLimitedError as e:
            self._note_rate_limit("manifest", e)
            return _RowCheck(row.row_number)   # not a row error: the whole run stops
        # YouTube rounds the length to whole seconds, so this catches most bad
        # ranges before downloading; stage 6 checks the real file again.
        if parsed.end_s > info.duration_s:
            result.messages.append((Level.ERROR, f"skipped: end time {parsed.end_s} s is past the "
                                    f"video's length ({info.duration_s:.0f} s)"))
            return result
        result.entry = ManifestEntry(parsed.row_number, parsed.title, parsed.artist, parsed.url,
                                     float(parsed.start_s), float(parsed.end_s), parsed.already_mirrored, info)
        result.messages.append((Level.INFO, f"ok: {result.entry.display_name} ({parsed.start_s}-{parsed.end_s} s"
                                f"{', already mirrored' if parsed.already_mirrored else ''})"))
        return result

    def _check_cached_row(self, parsed: ParsedRow, cached: Path, result: _RowCheck) -> _RowCheck:
        """A row whose file is cached: the file proves the video was available, and its
        length is measured (exact). The end time isn't checked here: stage 6 applies the
        usual rules to the exact length (trim within about 1 s, else a row error)."""
        try:
            # A tiny peak range keeps this fast; only the file's length is needed here.
            length = self._processor.measure(cached, 0.0, 0.1).duration_s
        except RenderError as e:
            result.messages.append((Level.ERROR, f"skipped: can't read the cached file {cached.name}: {e}"))
            return result
        media_id = cached.stem.rsplit("_", 1)[0]   # "<id>_audio" / "<id>_v720" (cache.cache_stem)
        result.entry = ManifestEntry(parsed.row_number, parsed.title, parsed.artist, parsed.url,
                                     float(parsed.start_s), float(parsed.end_s), parsed.already_mirrored,
                                     MediaInfo(media_id, "", length))
        result.from_cache = True
        result.messages.append((Level.INFO, f"ok: {result.entry.display_name} ({parsed.start_s}-{parsed.end_s} s"
                                f"{', already mirrored' if parsed.already_mirrored else ''}; cached, "
                                "not looked up)"))
        return result

    def _lookup_with_retries(self, url: str, max_retries: int,
                             note_retry: Callable[[str], None]) -> MediaInfo:
        """Look one video up, retrying retryable errors up to max_retries times (the
        same policy as downloads). note_retry gets a message for each retry.

        Raises:
            MediaUnavailableError: The last try failed, or the error isn't worth retrying.
            RateLimitedError: The media source is limiting the connection (never retried).
        """
        for attempt in range(max_retries + 1):
            try:
                return self._media.lookup(url)
            except MediaUnavailableError as e:
                if attempt == max_retries or not e.retryable:
                    raise
                wait = retry_wait_s(attempt, self._rng)
                note_retry(f"look-up retry {attempt + 1}/{max_retries} in {wait:.1f} s: {e}")
                self._pause(wait)
                if self._limited.is_set():   # another worker hit the rate limit meanwhile
                    raise RateLimitedError("not retried: the connection is being limited")
        raise AssertionError("unreachable: the loop always returns or raises")

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
        return self._check_countdown(path, kind)

    def _fetch_countdown(self, url: str, kind: MediaKind, cache_dir: Path, dl: DownloadSettings) -> Path:
        """A countdown URL goes through the media source like a song: same look-up,
        same cache name, same retries, and like a song it isn't looked up when it's
        cached. Only the failure differs: it stops the run."""
        cached = self._cached_file(url, kind, cache_dir)
        if cached:
            self._log(Level.INFO, "countdown", f"cached, not looked up: countdown ({cached.name})")
            return cached
        try:
            info = self._lookup_with_retries(
                url, dl.max_retries, lambda msg: self._log(Level.WARNING, "countdown", msg))
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

    def _check_countdown(self, path: Path, kind: MediaKind) -> Segment:
        info = self._processor.measure(path, 0.0, None)
        if not kind.audio_only and not info.has_video:
            # The countdown is measured once per run, so this warns once (SPEC §9 stage 3).
            self._log(Level.WARNING, "countdown", f"{path.name} has no picture: shown as a black "
                      "screen, with its sound")
        # A short countdown only shortens the crossfades next to it (_build_plan);
        # below this it can't hold even a one-frame crossfade.
        if info.duration_s < MIN_CLIP_S:
            raise LarbError(f"Countdown is {info.duration_s:.2f} s long; it must be at least "
                            f"{MIN_CLIP_S:.2f} s")
        self._warn_short_streams(info, info.duration_s, "countdown", "countdown", None)
        gain = self._gain_for(info.peak_db, "countdown", None)
        self._log(Level.INFO, "countdown", f"{path.name}: {info.duration_s:.2f} s, gain {gain:+.1f} dB")
        return Segment(path, 0.0, info.duration_s, mirror=False, gain_db=gain,   # countdowns never mirror
                       has_video=info.has_video)

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
            total = len(todo)
            self._log(Level.INFO, "download", f"Downloading {total} video(s), "
                      f"up to {dl.max_parallel_downloads} at once", progress=(0, total))
            done = 0
            done_lock = threading.Lock()

            def download(entry: ManifestEntry) -> tuple[ManifestEntry, Path | None]:
                nonlocal done
                if self._halted():   # downloads still waiting never start
                    return entry, None
                try:
                    path = self._download_one(entry, kind, cache_dir, dl.max_retries)
                except RateLimitedError as e:
                    self._note_rate_limit("download", e)
                    return entry, None   # not a row error: the whole run stops
                with done_lock:
                    done += 1
                    self._log(Level.DEBUG, "download", f"downloaded {done}/{total}", progress=(done, total))
                return entry, path

            with ThreadPoolExecutor(max_workers=dl.max_parallel_downloads) as pool:
                # A StoppedError from a worker comes out here; leaving the "with" still
                # waits for the other downloads, which stop too (the media source is cancelled).
                for entry, path in pool.map(download, todo):
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

        Emits one "started" and one "ended" Activity event however many tries it
        takes, so the GUI shows one line per download.

        Raises:
            DownloadError: The last try failed, or the error isn't worth retrying.
            StoppedError: The run was stopped; what the download left behind is removed.
            RateLimitedError: The media source is limiting the connection (never
                retried); what the download left behind is removed.
        """
        self._log_activity(Activity(stem, name, started=True), row)
        try:
            for attempt in range(max_retries + 1):
                self._check_stop()
                try:
                    path = self._media.download(url, kind, cache_dir, stem)
                    self._log(Level.INFO, "download", f"done: {name} ({path.name})", row)
                    return path
                except DownloadError as e:
                    if attempt == max_retries or not e.retryable:
                        raise
                    wait = retry_wait_s(attempt, self._rng)
                    self._log(Level.WARNING, "download", f"retry {attempt + 1}/{max_retries} in {wait:.1f} s: "
                              f"{name}: {e}", row)
                    self._pause(wait)
                    if self._limited.is_set():   # another worker hit the rate limit meanwhile
                        raise RateLimitedError("not retried: the connection is being limited")
            raise AssertionError("unreachable: the loop always returns or raises")
        except (StoppedError, RateLimitedError):
            for path in remove_leftovers(cache_dir, stem):
                self._log(Level.INFO, "download", f"removed unfinished download {path.name}", row)
            raise
        finally:
            self._log_activity(Activity(stem, name, started=False), row)

    def _log_activity(self, activity: Activity, row: int | None) -> None:
        """A marker for the GUI's active-download lines. DEBUG: the log file keeps it,
        the console and the GUI's log don't show it."""
        what = "started" if activity.started else "ended"
        self._events.emit(LogEvent(Level.DEBUG, "download", f"{what}: {activity.label}", row,
                                   activity=activity))

    def _measure_songs(self, entries, paths: dict[str, Path], settings: Settings,
                       kind: MediaKind) -> list[tuple[ManifestEntry, Segment]]:
        segments = []
        todo = [entry for entry in entries if entry.media.media_id in paths]  # failed ones are reported
        for n, entry in enumerate(todo, 1):
            self._check_stop()
            # DEBUG: progress for the GUI's label, too many lines for the console.
            self._log(Level.DEBUG, "measure", f"measuring {n}/{len(todo)}", entry.row_number,
                      progress=(n - 1, len(todo)))
            path = paths[entry.media.media_id]
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
            # A short clip only shortens its crossfades (_build_plan); below this it
            # can't hold even a one-frame crossfade on both sides.
            if end - start < MIN_CLIP_S:
                self._log(Level.ERROR, "measure", f"skipped: clip is {end - start:.2f} s, "
                          f"shorter than {MIN_CLIP_S:.2f} s", entry.row_number)
                continue
            self._warn_short_streams(info, end - start, "measure", entry.display_name, entry.row_number)
            if not kind.audio_only and not info.has_video:
                self._log(Level.WARNING, "measure", f"{entry.display_name}: {path.name} has no picture: "
                          "shown as a black screen, with its sound", entry.row_number)
            mirror = settings.processing.mirror and not entry.already_mirrored  # SPEC §8 Mirror rule
            gain = self._gain_for(info.peak_db, "measure", entry.row_number)
            segments.append((entry, Segment(path, start, end, mirror, gain, has_video=info.has_video)))
            self._log(Level.DEBUG, "measure", f"{entry.display_name}: {start:.1f}-{end:.1f} s, "
                      f"peak {info.peak_db:.1f} dB -> gain {gain:+.1f} dB, mirror {mirror}", entry.row_number)
        return segments

    def _build_plan(self, countdown: Segment, songs: list[tuple[ManifestEntry, Segment]],
                    setting_s: float, kind: MediaKind) -> RenderPlan:
        """Countdown before every song, crossfaded at every join, fading out at the end.

        A join's crossfade is shortened when a clip next to it is too short to hold
        the setting (plan_crossfades). Each song that causes that gets a row warning;
        the countdown, which is the same clip every time, gets one warning per run.
        """
        segments = []
        for _, song in songs:
            segments += [countdown, song]
        durations = [s.duration_s for s in segments]
        crossfades, fade_out = plan_crossfades(durations, setting_s)
        # The end fade-out follows the same rule as a crossfade: hard-coded, not a setting (SPEC §9 stage 7).
        limits = crossfade_limits(durations, fade_out=True)

        countdown_limit = min(limits[0::2])
        if countdown_limit < setting_s:
            self._log(Level.WARNING, "render", f"Countdown is only {countdown.duration_s:.2f} s: crossfades "
                      f"next to it shortened to {countdown_limit:.2f} s (setting {setting_s:g} s)")
        for (entry, song), limit in zip(songs, limits[1::2]):
            if limit < setting_s:
                self._log(Level.WARNING, "render", f"{entry.display_name}: clip is only "
                          f"{song.duration_s:.2f} s: crossfades next to it shortened to {limit:.2f} s "
                          f"(setting {setting_s:g} s)", entry.row_number)
        return RenderPlan(tuple(segments), crossfades, kind.audio_only, kind.max_height, fade_out_s=fade_out)

    def _warn_short_streams(self, info: ClipInfo, clip_s: float, stage: str, name: str,
                            row: int | None) -> None:
        """The renderer pads a stream that ends early (silence, or the last frame
        repeated), so the output keeps its planned length. A few ms is normal (TECH §16);
        more than SHORT_STREAM_WARN_S may be a real problem, e.g. a frozen picture.

        Args:
            info: Measured over the clip's range (padding included).
            clip_s: The clip's planned length.
        """
        for stream, available, filler in (("video", info.video_s, "the last frame is repeated"),
                                          ("audio", info.audio_s, "silence is added")):
            if available is not None and clip_s - available > SHORT_STREAM_WARN_S:
                self._log(Level.WARNING, stage, f"{name}: {stream} is {clip_s - available:.2f} s shorter "
                          f"than the clip ({clip_s:.2f} s); {filler}", row)

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
        return _free_name(output_dir / f"{name}{ext}")

    def _remove_leftover_renders(self, output_dir: Path) -> None:
        """Delete temporary outputs left by a run that crashed or was killed.

        Only <name>.rendering.mp3 / .mp4 files, the only temporary files a run puts in
        the output folder: the operator may point it at a folder with their own files.
        A file another run is still writing can't be deleted on Windows; it's skipped.
        """
        for pattern in (f"*{RENDERING_SUFFIX}.mp3", f"*{RENDERING_SUFFIX}.mp4"):
            for path in output_dir.glob(pattern):
                if not path.is_file():
                    continue
                try:
                    path.unlink()
                    self._log(Level.INFO, "output", f"Removed a leftover unfinished output: {path.name}")
                except OSError as e:
                    self._log(Level.WARNING, "output", f"Can't remove leftover {path.name} "
                              f"(another run may still be writing it): {e}")

    def _render_checked(self, plan: RenderPlan, output: Path) -> Path:
        """Render to a temporary name, check the result, then name it.

        Rule: nothing unverified ever gets the final name. A render that passes the
        length check is renamed to `output`; one that fails the check, or that fails
        after writing something, is renamed to <name>_FAILED.<ext> and the run stops.

        Returns:
            Where the output ended up (`output`, or the next free name if that has
            appeared in the meantime).

        Raises:
            RenderError: Rendering failed or the result doesn't match the plan.
        """
        rendering = output.with_name(f"{output.stem}{RENDERING_SUFFIX}{output.suffix}")
        try:
            self._processor.render(plan, rendering)
            self._verify_output(rendering, plan)
        except RenderError as e:
            raise RenderError(f"{e}{self._keep_failed(rendering, output)}") from None
        except StoppedError:
            # A stopped render is unverified like a failed one (SPEC §9).
            note = self._keep_failed(rendering, output)
            if note:
                self._log(Level.INFO, "render", note.strip())
            raise
        final = _free_name(output)   # never overwrite an earlier output
        rendering.rename(final)
        return final

    def _keep_failed(self, rendering: Path, output: Path) -> str:
        """Rename a failed render to <name>_FAILED.<ext>, so it can be inspected but never
        mistaken for a good result. Returns a note for the error message."""
        if not rendering.is_file():
            return ""
        if rendering.stat().st_size == 0:    # nothing was written: nothing worth keeping
            rendering.unlink(missing_ok=True)
            return ""
        failed = _free_name(output.with_name(f"{output.stem}{FAILED_SUFFIX}{output.suffix}"))
        rendering.rename(failed)
        return f"\nThe rejected file was kept as {failed}"

    def _verify_output(self, output: Path, plan: RenderPlan) -> None:
        """Goal 1: FFmpeg can succeed and still write a wrong file, so check the length."""
        if not output.is_file():
            raise RenderError(f"The renderer reported success but {output} doesn't exist")
        # A tiny peak range keeps this fast; only the real length matters here.
        actual = self._processor.measure(output, 0.0, 0.1).duration_s
        expected = plan.expected_duration_s
        if abs(actual - expected) > LENGTH_TOLERANCE_S:
            raise RenderError(f"Output is {actual:.2f} s long but should be {expected:.2f} s")
        self._log(Level.INFO, "render", f"Length check ok: {actual:.2f} s (planned {expected:.2f} s)")


def _free_name(path: Path) -> Path:
    """path if nothing is there yet, else the first free <stem>_2, _3, ... in the same folder."""
    candidate, n = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        n += 1
    return candidate
