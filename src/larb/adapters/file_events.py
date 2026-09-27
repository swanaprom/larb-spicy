"""EventSinks for the per-run log file, and for sending events to several sinks at once.

Every run writes workspace/logs/<date>_<time>.log. Only the newest few are kept
(SPEC §11): old ones are deleted when a run starts.
"""

import re
import threading
from datetime import datetime
from pathlib import Path

from larb.core.models import LogEvent
from larb.core.ports import EventSink

KEEP_LOGS = 5   # log files kept, the current run's included (SPEC §11)

# "2026-09-27_143012.log", or "2026-09-27_143012_2.log" for a second run in the same second.
_LOG_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{6})(?:_(\d+))?\.log$")


def _age_key(path: Path) -> tuple[str, str, int]:
    date, time, n = _LOG_NAME_RE.match(path.name).groups()
    return date, time, int(n or 1)


def prune_logs(log_dir: Path, keep: int) -> list[Path]:
    """Delete all but the `keep` newest log files in log_dir; return the deleted ones.

    "Newest" goes by the date and time in the file name, not the file's modified
    time (which copying or syncing can change). Files not named like a log are
    never touched.
    """
    if not log_dir.is_dir():
        return []
    logs = sorted((p for p in log_dir.iterdir() if p.is_file() and _LOG_NAME_RE.match(p.name)),
                  key=_age_key)
    old = logs[:-keep] if keep > 0 else logs
    for path in old:
        path.unlink()
    return old


def new_log_path(log_dir: Path, now: datetime) -> Path:
    """A new log file name for a run started at `now`; never an existing file."""
    name = f"{now:%Y-%m-%d}_{now:%H%M%S}"   # no ":" (illegal in Windows file names)
    path, n = log_dir / f"{name}.log", 2
    while path.exists():
        path = log_dir / f"{name}_{n}.log"
        n += 1
    return path


class FileEventSink(EventSink):
    """Writes every event, DEBUG included, to one log file.

    The file always gets DEBUG (e.g. the exact FFmpeg commands), whatever the
    console shows, so a failed run can be investigated afterwards.

    Args:
        log_dir: Folder for the log files (created if missing).
        now: When the run started; names the file.
    """

    def __init__(self, log_dir: Path, now: datetime | None = None) -> None:
        log_dir.mkdir(parents=True, exist_ok=True)
        # Make room first, so the folder never holds more than KEEP_LOGS files.
        prune_logs(log_dir, KEEP_LOGS - 1)
        self.path = new_log_path(log_dir, now or datetime.now())
        self._file = open(self.path, "w", encoding="utf-8")
        self._lock = threading.Lock()   # downloads log from several threads at once

    def emit(self, event: LogEvent) -> None:
        row = f"row {event.row_number}: " if event.row_number is not None else ""
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {event.level.name:<7} {event.stage:<9} {row}{event.message}"
        with self._lock:
            if not self._file.closed:
                self._file.write(line + "\n")
                self._file.flush()   # keep the log complete even if the program crashes

    def close(self) -> None:
        with self._lock:
            self._file.close()


class MultiEventSink(EventSink):
    """Passes every event on to several sinks (e.g. the console and the log file)."""

    def __init__(self, *sinks: EventSink) -> None:
        self._sinks = sinks

    def emit(self, event: LogEvent) -> None:
        for sink in self._sinks:
            sink.emit(event)
