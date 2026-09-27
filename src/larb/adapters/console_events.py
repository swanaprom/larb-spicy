"""EventSink that prints to the console (the GUI replaces it later)."""

import sys
import threading
from datetime import datetime

from larb.core.models import Level, LogEvent
from larb.core.ports import EventSink


class ConsoleEventSink(EventSink):
    """Args:
        min_level: Events below this level aren't printed (DEBUG shows FFmpeg commands).
    """

    def __init__(self, min_level: Level = Level.INFO) -> None:
        self._min_level = min_level
        self._lock = threading.Lock()  # downloads log from several threads at once

    def emit(self, event: LogEvent) -> None:
        if event.level.value < self._min_level.value:
            return
        row = f"row {event.row_number}: " if event.row_number is not None else ""
        line = f"{datetime.now():%H:%M:%S} {event.level.name:<7} {event.stage:<9} {row}{event.message}"
        with self._lock:
            print(line, file=sys.stderr if event.level is Level.ERROR else sys.stdout, flush=True)
