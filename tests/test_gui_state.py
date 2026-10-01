"""The window's decisions (slice 5), tested without opening a window: what's enabled,
the progress label, log counts and filter, active downloads, and turning the fields
into a run. The worker thread is tested with a fake pipeline."""

import queue
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import ROOT  # noqa: E402  (also puts src/ on the path)
from larb.core.errors import LarbError, StoppedError  # noqa: E402
from larb.core.models import (Activity, Level, LogEvent, OutputSettings, ProcessingSettings,  # noqa: E402
                              RowRange, Settings)
from larb.gui import runner  # noqa: E402
from larb.gui.state import (ActiveDownloads, Fields, LogCounts, LogFilter, Phase,  # noqa: E402
                            ProgressView, bottom_row, cache_reminder, clear_cache_question, controls,
                            elapsed, log_line, run_request, settings_from_fields, shown_in_log,
                            size_text, stop_reason, visible)

PROJECT = ROOT
WORKSPACE = ROOT / "workspace"


def fields(**changes) -> Fields:
    base = dict(source="https://sheet", rows_from="", rows_to="", audio_only=True, mirror=False,
                countdown="", crossfade="0.8", output_dir=str(WORKSPACE / "output"))
    base.update(changes)
    return Fields(**base)


class ControlsTest(unittest.TestCase):
    def test_idle(self):
        c = controls(Phase.IDLE, audio_only=False)
        self.assertTrue(c.inputs and c.mirror and c.run_button and c.clear_cache)
        self.assertFalse(c.run_is_stop or c.open_output)

    def test_mirror_greyed_for_audio(self):
        self.assertFalse(controls(Phase.IDLE, audio_only=True).mirror)

    def test_running_locks_everything_that_could_change_the_run(self):
        c = controls(Phase.RUNNING, audio_only=False)
        self.assertFalse(c.inputs or c.mirror or c.clear_cache or c.open_output)
        self.assertTrue(c.run_is_stop and c.run_button)

    def test_stopping_waits(self):
        c = controls(Phase.STOPPING, audio_only=False)
        self.assertTrue(c.run_is_stop)
        self.assertFalse(c.run_button or c.inputs)

    def test_open_only_after_success(self):
        self.assertTrue(controls(Phase.FINISHED, True).open_output)
        self.assertFalse(controls(Phase.FAILED, True).open_output)
        self.assertTrue(controls(Phase.FAILED, True).inputs)   # unlocked again


class RunRequestTest(unittest.TestCase):
    def test_fields_become_a_run(self):
        request = run_request(fields(source=' "https://sheet" ', rows_from="3", crossfade="abc",
                                     audio_only=False, mirror=True), Settings(), PROJECT, WORKSPACE)
        self.assertEqual(request.source, "https://sheet")        # quotes from a pasted path dropped
        self.assertEqual(request.rows, RowRange(3, None))
        self.assertIsNone(request.countdown)                     # empty = the default countdown
        p = request.settings.processing
        self.assertEqual((p.audio_only, p.mirror, p.crossfade_duration_seconds), (False, True, 0.8))
        self.assertEqual(request.settings.output.directory, "")  # the default folder is saved as ""

    def test_needs_a_sheet(self):
        with self.assertRaisesRegex(LarbError, "Google Sheet link"):
            run_request(fields(source="  "), Settings(), PROJECT, WORKSPACE)

    def test_bad_rows(self):
        with self.assertRaisesRegex(LarbError, "backwards"):
            run_request(fields(rows_from="9", rows_to="3"), Settings(), PROJECT, WORKSPACE)

    def test_file_only_settings_are_kept(self):
        loaded = Settings(output=OutputSettings(filename_template="{date}"))
        elsewhere = Path(PROJECT.anchor) / "renders"   # an absolute folder on any OS
        settings = settings_from_fields(fields(output_dir=str(elsewhere)), loaded, PROJECT, WORKSPACE)
        self.assertEqual(settings.output.filename_template, "{date}")
        self.assertEqual(settings.download, loaded.download)
        self.assertEqual(Path(settings.output.directory), elsewhere)

    def test_unchanged_fields_mean_no_unsaved_edits(self):
        loaded = Settings(processing=ProcessingSettings(audio_only=True, crossfade_duration_seconds=0.8))
        self.assertEqual(settings_from_fields(fields(), loaded, PROJECT, WORKSPACE), loaded)
        self.assertNotEqual(settings_from_fields(fields(crossfade="1.5"), loaded, PROJECT, WORKSPACE), loaded)


class ProgressViewTest(unittest.TestCase):
    def test_follows_the_stages(self):
        """Label and bar through a run. None = the bar sweeps: a step without numbers,
        or nothing done yet (the bar is never empty and still, GUI.md 2.3)."""
        view = ProgressView()
        view.start()
        seen = [(view.text, view.fraction)]
        for event in (LogEvent(Level.INFO, "sheet", "Reading song list: x"),
                      LogEvent(Level.INFO, "countdown", "cached: countdown"),
                      LogEvent(Level.INFO, "manifest", "Checking 40 row(s)", progress=(0, 40)),
                      LogEvent(Level.INFO, "manifest", "checked 10/40", 5, progress=(10, 40)),
                      LogEvent(Level.INFO, "manifest", "row 5 ok"),           # no numbers: no change
                      LogEvent(Level.INFO, "download", "Downloading 40", progress=(0, 40)),
                      LogEvent(Level.DEBUG, "download", "downloaded 20/40", progress=(20, 40)),
                      LogEvent(Level.DEBUG, "measure", "measuring 3/40", progress=(2, 40)),
                      LogEvent(Level.INFO, "render", "Rendering 40 song(s)"),
                      LogEvent(Level.DEBUG, "render", "rendered 63%", progress=(63_900, 100_000)),
                      LogEvent(Level.INFO, "render", "video part 3/7 written; checking it"),
                      LogEvent(Level.INFO, "render", "rendered 70%", progress=(70_000, 100_000)),
                      LogEvent(Level.INFO, "render", "joining the video parts and the audio")):
            view.update(event)
            seen.append((view.text, view.fraction))
        self.assertEqual(seen, [("Starting", None), ("Reading the sheet", None),
                                ("Preparing the countdown", None), ("Checking 0 / 40", None),
                                ("Checking 10 / 40", 0.25), ("Checking 10 / 40", 0.25),
                                ("Downloading 0 / 40", None), ("Downloading 20 / 40", 0.5),
                                ("Measuring 2 / 40", 0.05), ("Rendering", None),
                                ("Rendering 63%", 0.639), ("Rendering", None),
                                ("Rendering 70%", 0.7), ("Rendering", None)])

    def test_render_percentage_for_audio_and_video(self):
        """The same events in both modes: milliseconds of planned output written."""
        view = ProgressView()
        view.update(LogEvent(Level.DEBUG, "render", "rendered 1%", progress=(1_400, 140_020)))
        self.assertEqual((view.text, round(view.fraction, 3)), ("Rendering 0%", 0.01))
        view.update(LogEvent(Level.INFO, "render", "rendered 100%", progress=(140_020, 140_020)))
        self.assertEqual((view.text, view.fraction), ("Rendering 100%", 1.0))

    def test_stopping_sweeps(self):
        view = ProgressView()
        view.update(LogEvent(Level.INFO, "manifest", "checked 10/40", 5, progress=(10, 40)))
        view.stopping()
        self.assertEqual((view.text, view.fraction), ("Stopping...", None))

    def test_how_it_ended(self):
        view = ProgressView()
        view.finish(None)
        self.assertEqual((view.text, view.fraction, view.failed), ("Finished", 1.0, False))
        view.finish(StoppedError("Stopped by the operator"))
        self.assertEqual((view.text, view.failed), ("Stopped: you pressed Stop", True))
        view.finish(LarbError("The sheet can't be read (HTTP 401).\nmore"))
        self.assertEqual(view.text, "Stopped: The sheet can't be read (HTTP 401).")

    def test_stop_reason_first_line(self):
        self.assertEqual(stop_reason(LarbError("Invalid settings:\n  - x")), "Invalid settings:")


class LogTest(unittest.TestCase):
    def test_debug_stays_in_the_file(self):
        self.assertFalse(shown_in_log(LogEvent(Level.DEBUG, "download", "started: x",
                                               activity=Activity("k", "x", True))))
        self.assertTrue(shown_in_log(LogEvent(Level.INFO, "sheet", "x")))

    def test_filter(self):
        self.assertEqual([lvl for lvl in Level if lvl is not Level.DEBUG and visible(lvl, LogFilter.WARNINGS)],
                         [Level.WARNING, Level.ERROR])   # "Warnings" shows warnings and errors
        self.assertEqual([lvl for lvl in Level if visible(lvl, LogFilter.ERRORS)], [Level.ERROR])
        self.assertTrue(visible(Level.INFO, LogFilter.ALL))

    def test_counts(self):
        counts = LogCounts()
        for level in (Level.INFO, Level.WARNING, Level.WARNING, Level.ERROR):
            counts.add(LogEvent(level, "x", "y"))
        self.assertEqual((counts.warnings, counts.errors), (2, 1))

    def test_line(self):
        self.assertEqual(log_line(LogEvent(Level.WARNING, "manifest", "artist is empty", 4)),
                         ("WARNING", "manifest", "row 4: artist is empty"))


class ActiveDownloadsTest(unittest.TestCase):
    def mark(self, key, label, started):
        return LogEvent(Level.DEBUG, "download", "", activity=Activity(key, label, started))

    def test_lines_come_and_go_by_key(self):
        downloads = ActiveDownloads()
        downloads.update(self.mark("a_v720", "Ditto", True), now=100.0)
        downloads.update(self.mark("b_v720", "Ditto", True), now=130.0)       # same title, other video
        downloads.update(LogEvent(Level.INFO, "download", "done: Ditto"), now=131.0)   # text is ignored
        self.assertEqual(downloads.lines(now=142.0), [("a_v720", "Ditto", "0:42"), ("b_v720", "Ditto", "0:12")])
        downloads.update(self.mark("a_v720", "Ditto", False), now=143.0)
        self.assertEqual([key for key, _, _ in downloads.lines(now=143.0)], ["b_v720"])

    def test_elapsed(self):
        self.assertEqual([elapsed(s) for s in (0, 5.9, 42, 723, 3723)], ["0:00", "0:05", "0:42", "12:03", "1:02:03"])


class TextsTest(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(size_text(0), "0 MB")
        self.assertEqual(size_text(1), "1 MB")
        self.assertEqual(size_text(128 * 1024 ** 2), "128 MB")
        self.assertEqual(size_text(int(2.5 * 1024 ** 3)), "2.5 GB")

    def test_cache_texts(self):
        self.assertIsNone(cache_reminder(0, 0))
        self.assertEqual(cache_reminder(8, 3 * 1024 ** 3),
                         "The cache holds 8 file(s) (3.0 GB). Use Clear cache when you're done.")
        self.assertEqual(clear_cache_question(8, 128 * 1024 ** 2), "Delete 8 downloaded file(s) (128 MB)?")

    def test_bottom_row_mirrors_on_mac(self):
        self.assertEqual(bottom_row(mac=False), ["run", "est_length", "clear_cache"])
        self.assertEqual(bottom_row(mac=True), ["clear_cache", "est_length", "run"])


class FakePipeline:
    """Stands in for the real pipeline: emits a few events, then waits to be stopped."""

    def __init__(self, events):
        self.events = events
        self.stopped = threading.Event()

    def stop(self):
        self.stopped.set()

    def run(self, source, countdown, settings, rows=None):
        self.events.emit(LogEvent(Level.INFO, "sheet", f"Reading song list: {source}"))
        if not self.stopped.wait(10):
            raise AssertionError("never stopped")
        raise StoppedError("Stopped by the operator")


class RunWorkerTest(unittest.TestCase):
    """The worker thread: events and Done arrive on the queue; stop() reaches the pipeline."""

    def setUp(self):
        # Each run writes a log file (and prunes old ones): keep that out of workspace/logs.
        logs = Path(tempfile.mkdtemp(prefix="test_logs_", dir=WORKSPACE))
        self.addCleanup(shutil.rmtree, logs, True)
        patcher = mock.patch.object(runner.app, "LOG_DIR", logs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_stop_and_done(self):
        built = {}

        def build_run(store, events):
            built["pipeline"] = FakePipeline(events)
            return runner.app.Run(built["pipeline"], "yt-dlp test")

        request = run_request(fields(countdown="https://countdown"), Settings(), PROJECT, WORKSPACE)
        with mock.patch.object(runner.app, "build_run", build_run), \
                mock.patch.object(runner, "cache_summary", lambda folder: (2, 5 * 1024 ** 2)):
            worker = runner.RunWorker(store=None, request=request)
            worker.start()
            items = [worker.queue.get(timeout=10)]
            while not (isinstance(items[-1], LogEvent) and items[-1].stage == "sheet"):
                items.append(worker.queue.get(timeout=10))
            worker.stop()
            while not isinstance(items[-1], runner.Done):
                items.append(worker.queue.get(timeout=10))

        done = items[-1]
        self.assertIsInstance(done.error, StoppedError)
        self.assertIsNone(done.result)
        messages = [(e.level, e.stage) for e in items if isinstance(e, LogEvent)]
        self.assertIn((Level.WARNING, "stopped"), messages)
        self.assertEqual(messages[-1], (Level.WARNING, "cache"))   # the reminder is the last line
        self.assertTrue(built["pipeline"].stopped.is_set())

    def test_stop_before_the_pipeline_exists(self):
        """Stop pressed while the run is still being put together: it still stops."""
        release = threading.Event()

        def slow_build_run(store, events):
            release.wait(10)
            return runner.app.Run(FakePipeline(events), "yt-dlp test")

        request = run_request(fields(countdown="https://countdown"), Settings(), PROJECT, WORKSPACE)
        with mock.patch.object(runner.app, "build_run", slow_build_run), \
                mock.patch.object(runner, "cache_summary", lambda folder: (0, 0)):
            worker = runner.RunWorker(store=None, request=request)
            worker.start()
            time.sleep(0.1)
            worker.stop()
            release.set()
            done = None
            while done is None:
                item = worker.queue.get(timeout=10)
                done = item if isinstance(item, runner.Done) else None
        self.assertIsInstance(done.error, StoppedError)

    def test_an_unexpected_error_still_ends_the_run(self):
        def broken_build_run(store, events):
            raise KeyError("bug")

        request = run_request(fields(countdown="https://countdown"), Settings(), PROJECT, WORKSPACE)
        with mock.patch.object(runner.app, "build_run", broken_build_run), \
                mock.patch.object(runner, "cache_summary", lambda folder: (0, 0)):
            worker = runner.RunWorker(store=None, request=request)
            worker.start()
            items = []
            while not items or not isinstance(items[-1], runner.Done):
                items.append(worker.queue.get(timeout=10))
        self.assertIsInstance(items[-1].error, KeyError)
        self.assertTrue(any(isinstance(e, LogEvent) and e.level is Level.ERROR and "Unexpected error" in e.message
                            for e in items))


class QueueSinkTest(unittest.TestCase):
    def test_puts_events_on_the_queue(self):
        q = queue.Queue()
        event = LogEvent(Level.INFO, "x", "y")
        runner.QueueEventSink(q).emit(event)
        self.assertIs(q.get_nowait(), event)


if __name__ == "__main__":
    unittest.main()
