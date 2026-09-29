"""The window's decisions, in plain Python (no Tkinter), so they can be tested offline.

What's enabled, what the progress label says, the log counts, the active-download
lines, and turning the fields into a run: all here. window.py only draws what these
say (docs/GUI.md is the design).
"""

import math
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

from larb.core.errors import LarbError, StoppedError
from larb.core.manifest import row_range_from_fields
from larb.core.models import Level, LogEvent, RowRange, Settings
from larb.core.settings import correct_crossfade, folder_setting, resolve_folder


class Phase(Enum):
    IDLE = "idle"           # nothing run yet in this window
    RUNNING = "running"
    STOPPING = "stopping"   # Stop confirmed; waiting for the run to end
    FINISHED = "finished"   # the last run produced an output
    FAILED = "failed"       # the last run was stopped or aborted


@dataclass(frozen=True)
class Controls:
    """What the operator can use right now (GUI.md: locked during a run)."""

    inputs: bool          # the whole top pane
    mirror: bool          # also greyed out when Audio is selected
    run_is_stop: bool     # the Run button shows Stop
    run_button: bool
    clear_cache: bool
    open_output: bool     # Open file / Open folder


def controls(phase: Phase, audio_only: bool) -> Controls:
    busy = phase in (Phase.RUNNING, Phase.STOPPING)
    return Controls(
        inputs=not busy,
        mirror=not busy and not audio_only,   # mirroring only affects the picture
        run_is_stop=busy,
        run_button=phase is not Phase.STOPPING,   # stopping already; nothing more to press
        clear_cache=not busy,
        open_output=phase is Phase.FINISHED,
    )


# ---------------------------------------------------------------------------
# Fields -> a run
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Fields:
    """The top pane, as text and choices."""

    source: str
    rows_from: str
    rows_to: str
    audio_only: bool
    mirror: bool
    countdown: str
    crossfade: str
    output_dir: str   # shown as a full path


@dataclass(frozen=True)
class RunRequest:
    source: str
    rows: RowRange | None
    countdown: str | None   # None = the default countdown from the settings
    settings: Settings      # to save, then use for the whole run


def settings_from_fields(fields: Fields, loaded: Settings, project_dir: Path, workspace: Path) -> Settings:
    """The settings the fields describe. Keys the window doesn't show (file-only)
    keep the loaded values."""
    return replace(
        loaded,
        output=replace(loaded.output,
                       directory=folder_setting(fields.output_dir, "output", project_dir, workspace)),
        processing=replace(loaded.processing, audio_only=fields.audio_only, mirror=fields.mirror,
                           crossfade_duration_seconds=correct_crossfade(fields.crossfade)),
    )


def run_request(fields: Fields, loaded: Settings, project_dir: Path, workspace: Path) -> RunRequest:
    """Check the run inputs and build the run.

    Raises:
        LarbError: No sheet, or the row fields aren't a usable range.
    """
    source = fields.source.strip().strip('"')
    if not source:
        raise LarbError("Paste a Google Sheet link, or choose a CSV file with Browse.")
    rows = row_range_from_fields(fields.rows_from, fields.rows_to)
    countdown = fields.countdown.strip().strip('"') or None
    return RunRequest(source, rows, countdown, settings_from_fields(fields, loaded, project_dir, workspace))


def shown_folder(text: str, default_name: str, project_dir: Path, workspace: Path) -> str:
    """A folder field shows a full path (GUI.md), so the relative-path mistake can't happen."""
    return str(resolve_folder(text, default_name, project_dir, workspace))


# ---------------------------------------------------------------------------
# Progress label and bar
# ---------------------------------------------------------------------------

# Stage -> label words while counting (LogEvent.progress).
_COUNTED = {"manifest": "Checking", "download": "Downloading", "measure": "Measuring",
            "render": "Rendering part"}
# Stage -> label when a stage starts without a count.
_UNCOUNTED = {"sheet": "Reading the sheet", "countdown": "Preparing the countdown",
              "render": "Rendering"}


@dataclass
class ProgressView:
    """The overall bar and its label (GUI.md 2.3): follows the run stage by stage,
    then says how it ended."""

    text: str = ""
    fraction: float = 0.0
    failed: bool = False   # "Stopped: ..." is shown in RED

    def start(self) -> None:
        self.text, self.fraction, self.failed = "Starting", 0.0, False

    def update(self, event: LogEvent) -> None:
        if event.progress is not None and event.stage in _COUNTED:
            done, total = event.progress
            self.text = f"{_COUNTED[event.stage]} {done} / {total}"
            self.fraction = done / total if total else 0.0
        elif event.stage in _UNCOUNTED and event.level is Level.INFO:
            if event.stage == "render" and self.text.startswith(_COUNTED["render"]):
                return   # "Rendering part 3 / 7" stays until the next part
            if self.text != _UNCOUNTED[event.stage]:
                self.text, self.fraction = _UNCOUNTED[event.stage], 0.0

    def finish(self, error: Exception | None) -> None:
        if error is None:
            self.text, self.fraction, self.failed = "Finished", 1.0, False
        else:
            self.text, self.failed = f"Stopped: {stop_reason(error)}", True


def stop_reason(error: Exception) -> str:
    """The reason after "Stopped: ", first line only (the pop-up has the whole message)."""
    if isinstance(error, StoppedError):
        return "you pressed Stop"
    lines = str(error).strip().splitlines()
    return lines[0] if lines else type(error).__name__


# ---------------------------------------------------------------------------
# Log panel: filter and counts
# ---------------------------------------------------------------------------

class LogFilter(Enum):
    ALL = "all"
    WARNINGS = "warnings"   # warnings and errors
    ERRORS = "errors"


def shown_in_log(event: LogEvent) -> bool:
    """DEBUG is only in the log file (GUI.md 2.2); markers and counts are DEBUG too."""
    return event.level is not Level.DEBUG


def visible(level: Level, log_filter: LogFilter) -> bool:
    if log_filter is LogFilter.ERRORS:
        return level is Level.ERROR
    if log_filter is LogFilter.WARNINGS:
        return level in (Level.WARNING, Level.ERROR)
    return True


@dataclass
class LogCounts:
    warnings: int = 0
    errors: int = 0

    def add(self, event: LogEvent) -> None:
        if event.level is Level.WARNING:
            self.warnings += 1
        elif event.level is Level.ERROR:
            self.errors += 1


def log_line(event: LogEvent) -> tuple[str, str, str]:
    """(level, stage, text) of one log line; the window adds the time."""
    row = f"row {event.row_number}: " if event.row_number is not None else ""
    return event.level.name, event.stage, row + event.message


# ---------------------------------------------------------------------------
# Active downloads
# ---------------------------------------------------------------------------

@dataclass
class ActiveDownloads:
    """One line per download in progress, from the core's Activity markers
    (never from log text). Keyed, because two songs can share a title."""

    _started: dict[str, tuple[str, float]] = field(default_factory=dict)   # key -> (label, start)

    def update(self, event: LogEvent, now: float) -> None:
        activity = event.activity
        if activity is None:
            return
        if activity.started:
            self._started[activity.key] = (activity.label, now)
        else:
            self._started.pop(activity.key, None)

    def clear(self) -> None:
        self._started.clear()

    def lines(self, now: float) -> list[tuple[str, str, str]]:
        """(key, label, elapsed "m:ss"), oldest first."""
        return [(key, label, elapsed(now - start)) for key, (label, start) in self._started.items()]


def elapsed(seconds: float) -> str:
    """0:05, 0:42, 12:03, 1:02:03."""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


# ---------------------------------------------------------------------------
# Cache texts, bottom row
# ---------------------------------------------------------------------------

def size_text(n_bytes: int) -> str:
    """Megabytes below a gigabyte, else gigabytes with one decimal."""
    if n_bytes >= 1024 ** 3:
        return f"{n_bytes / 1024 ** 3:.1f} GB"
    return f"{math.ceil(n_bytes / 1024 ** 2)} MB" if n_bytes else "0 MB"


def cache_reminder(files: int, n_bytes: int) -> str | None:
    """The WARNING at the end of each run's log (GUI.md 3.3); None for an empty cache."""
    if not files:
        return None
    return f"The cache holds {files} file(s) ({size_text(n_bytes)}). Use Clear cache when you're done."


def clear_cache_question(files: int, n_bytes: int) -> str:
    return f"Delete {files} downloaded file(s) ({size_text(n_bytes)})?"


def bottom_row(mac: bool) -> list[str]:
    """Left to right. Run is where the eye lands first on Windows and Linux (left);
    Mac mirrors the row (GUI.md)."""
    row = ["run", "est_length", "clear_cache"]
    return row[::-1] if mac else row
