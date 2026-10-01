"""Runs the pipeline on a worker thread for the window (TECH §6).

The worker never touches a widget. Everything it has to say goes on one queue:
the core's log events, then a Done message. The window drains that queue on its own
thread (Tk's `after`), which is the only thread that updates widgets.
"""

import queue
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path

from larb import app
from larb.adapters.file_events import FileEventSink, MultiEventSink
from larb.adapters.toml_settings import TomlSettingsStore
from larb.core.cache import cache_summary
from larb.core.errors import LarbError, StoppedError
from larb.core.models import LengthEstimate, Level, LogEvent, RunResult
from larb.core.pipeline import Pipeline
from larb.core.ports import EventSink
from larb.gui.state import RunRequest, cache_reminder


class QueueEventSink(EventSink):
    """EventSink for the window: puts each event on a queue (queue.Queue is thread-safe)."""

    def __init__(self, q: "queue.Queue") -> None:
        self._queue = q

    def emit(self, event: LogEvent) -> None:
        self._queue.put(event)


@dataclass(frozen=True)
class Done:
    """The run (or estimate) ended. Exactly one of result / error is set."""

    result: RunResult | LengthEstimate | None
    error: Exception | None


class _Worker:
    """Pipeline work on a background thread. Start it, maybe stop it, wait for Done on `queue`.

    Args:
        store: The settings store the window loaded (the sheet adapter reads its
            [sheet.columns]).
    """

    def __init__(self, store: TomlSettingsStore, request: RunRequest, name: str) -> None:
        self.queue: queue.Queue = queue.Queue()
        self._store = store
        self._request = request
        self._lock = threading.Lock()
        self._pipeline: Pipeline | None = None
        self._stop_asked = False
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """Ask the work to stop; returns at once. Done still arrives on the queue."""
        with self._lock:
            self._stop_asked = True
            pipeline = self._pipeline
        if pipeline is not None:
            pipeline.stop()

    def _attach(self, pipeline: Pipeline) -> None:
        """Make the pipeline stoppable; stop it now if Stop came while it was being built."""
        with self._lock:
            self._pipeline = pipeline
            stop_now = self._stop_asked
        if stop_now:
            pipeline.stop()

    def _run(self) -> None:
        raise NotImplementedError


class RunWorker(_Worker):
    """One run."""

    def __init__(self, store: TomlSettingsStore, request: RunRequest) -> None:
        super().__init__(store, request, "larb-run")

    def _run(self) -> None:
        log_file = FileEventSink(app.LOG_DIR)
        events = MultiEventSink(QueueEventSink(self.queue), log_file)
        result, error = None, None
        request = self._request
        try:
            events.emit(LogEvent(Level.INFO, "start", f"Log file: {log_file.path}"))
            countdown = app.countdown_for_run(request.countdown, request.settings)
            run = app.build_run(self._store, events)
            self._attach(run.pipeline)
            events.emit(LogEvent(Level.INFO, "start", f"{run.tools_text}, settings: {app.CONFIG_FILE}"))
            result = run.pipeline.run(request.source, countdown, request.settings, rows=request.rows)
            events.emit(LogEvent(Level.INFO, "finished", f"{result.songs_rendered} song(s) -> "
                                 f"{result.output_path} ({result.row_errors} row error(s), "
                                 f"{result.row_warnings} warning(s))"))
        except StoppedError as e:
            error = e
            events.emit(LogEvent(Level.WARNING, "stopped", str(e)))
        except LarbError as e:
            error = e
            events.emit(LogEvent(Level.ERROR, "abort", str(e)))
        except Exception as e:   # a bug: still end the run cleanly and keep the details in the log
            error = e
            events.emit(LogEvent(Level.ERROR, "abort", f"Unexpected error: {e!r}"))
            events.emit(LogEvent(Level.DEBUG, "abort", traceback.format_exc()))
        finally:
            self._remind_cache(events)
            log_file.close()
            self.queue.put(Done(result, error))

    def _remind_cache(self, events: EventSink) -> None:
        """No question after a run in the window; a reminder line instead (SPEC §10)."""
        try:
            files, size = cache_summary(cache_folder(self._request.settings.download.cache_directory))
        except OSError:
            return
        reminder = cache_reminder(files, size)
        if reminder:
            events.emit(LogEvent(Level.WARNING, "cache", reminder))


class EstimateWorker(_Worker):
    """Est. Length (GUI.md 3.2).

    No log file: an estimate isn't a run, and the log folder keeps only the 5 newest
    files, so estimates would push real runs out. Its events still go on `queue`, for
    the progress label and the countdown's download line; the window logs only the result.
    """

    def __init__(self, store: TomlSettingsStore, request: RunRequest) -> None:
        super().__init__(store, request, "larb-estimate")

    def _run(self) -> None:
        events = QueueEventSink(self.queue)
        result, error = None, None
        request = self._request
        try:
            countdown = app.countdown_for_run(request.countdown, request.settings)
            run = app.build_run(self._store, events)
            self._attach(run.pipeline)
            result = run.pipeline.estimate(request.source, countdown, request.settings, rows=request.rows)
        except LarbError as e:   # StoppedError included: the window was closed
            error = e
        except Exception as e:   # a bug: still end cleanly and say what happened
            error = LarbError(f"Unexpected error: {e!r}")
            traceback.print_exc()   # no log file for an estimate: the details go to the console
        finally:
            self.queue.put(Done(result, error))


def cache_folder(setting: str) -> Path:
    return app.folder(setting, "cache")
