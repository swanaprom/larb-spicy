"""Est. Length in the window (slice 7, GUI.md 3.2): when the button can be used, the
pop-up's wording, the one log line, and the worker. No real pipeline here: the core is
tested in test_estimate.py."""

import queue
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import ROOT, close_root  # noqa: E402  (also puts src/ on the path)
from larb.adapters.toml_settings import TomlSettingsStore  # noqa: E402
from larb.core.errors import LarbError, StoppedError  # noqa: E402
from larb.core.manifest import BAD_TIME_RANGE, URL_EMPTY  # noqa: E402
from larb.core.models import LengthEstimate, Level, LogEvent, Settings  # noqa: E402
from larb.gui import runner, window  # noqa: E402
from larb.gui.runner import Done  # noqa: E402
from larb.gui.state import (Phase, ProgressView, controls, estimate_log_line, estimate_message,  # noqa: E402
                            length_text)

ESTIMATE = LengthEstimate(6380.0, 40, 30, ((BAD_TIME_RANGE, 2), (URL_EMPTY, 1)))


class ButtonTest(unittest.TestCase):
    def test_needs_a_sheet(self):
        self.assertFalse(controls(Phase.IDLE, True, sheet_filled=False).est_length)
        self.assertTrue(controls(Phase.IDLE, True, sheet_filled=True).est_length)

    def test_usable_after_any_run(self):
        for phase in (Phase.FINISHED, Phase.FAILED):
            self.assertTrue(controls(phase, True, sheet_filled=True).est_length)

    def test_not_during_a_run(self):
        for phase in (Phase.RUNNING, Phase.STOPPING):
            self.assertFalse(controls(phase, True, sheet_filled=True).est_length)

    def test_estimating_locks_like_a_run(self):
        c = controls(Phase.ESTIMATING, audio_only=False, sheet_filled=True)
        self.assertFalse(c.inputs or c.mirror or c.run_button or c.clear_cache or c.est_length
                         or c.open_output or c.run_is_stop)


class WordingTest(unittest.TestCase):
    def test_length_text(self):
        self.assertEqual(length_text(6380), "1 hour 46 min 20 s")
        self.assertEqual(length_text(7200.4), "2 hours 0 min 0 s")
        self.assertEqual(length_text(125), "2 min 5 s")
        self.assertEqual(length_text(44.6), "45 s")

    def test_popup(self):
        self.assertEqual(estimate_message(ESTIMATE),
                         "Estimated: 1 hour 46 min 20 s\n"
                         "2 rows left out (time range can't be read)\n"
                         "1 row left out (URL is empty)")

    def test_popup_without_left_out_rows(self):
        self.assertEqual(estimate_message(LengthEstimate(125.0, 3, 3)), "Estimated: 2 min 5 s")

    def test_popup_without_songs(self):
        message = estimate_message(LengthEstimate(0.0, 0, 0, ((BAD_TIME_RANGE, 1),)))
        self.assertEqual(message, "No usable songs: nothing would be rendered.\n"
                                  "1 row left out (time range can't be read)")

    def test_log_line_is_one_line(self):
        line = estimate_log_line(ESTIMATE)
        self.assertNotIn("\n", line)
        self.assertEqual(line, "Estimated length: 1 hour 46 min 20 s (40 song(s): 30 measured from the "
                               "cache, 10 from their time ranges); 2 rows left out (time range can't be "
                               "read); 1 row left out (URL is empty)")

    def test_progress_label(self):
        view = ProgressView()
        view.estimating()
        self.assertEqual((view.text, view.fraction), ("Estimating length", None))
        view.update(LogEvent(Level.DEBUG, "estimate", "checked 3/12", progress=(3, 12)))
        self.assertEqual(view.text, "Checking 3 / 12")


class FakeEstimatePipeline:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
        self.stopped = threading.Event()
        self.calls = []

    def estimate(self, source, countdown, settings, rows=None):
        self.calls.append((source, countdown, rows))
        if self.error:
            raise self.error
        return self.result

    def stop(self):
        self.stopped.set()


class EstimateWorkerTest(unittest.TestCase):
    def request(self):
        from larb.gui.state import RunRequest
        return RunRequest("https://sheet", None, None, Settings())

    def finish(self, pipeline):
        build = lambda store, events: runner.app.Run(pipeline, "yt-dlp test")  # noqa: E731
        with mock.patch.object(runner.app, "build_run", build), \
                mock.patch.object(runner.app, "countdown_for_run", return_value="https://cd"), \
                mock.patch.object(runner, "FileEventSink") as file_sink:
            worker = runner.EstimateWorker(mock.Mock(), self.request())
            worker.start()
            done = worker.queue.get(timeout=5)
            while not isinstance(done, Done):
                done = worker.queue.get(timeout=5)
        file_sink.assert_not_called()   # an estimate writes no log file
        return done

    def test_result(self):
        pipeline = FakeEstimatePipeline(result=ESTIMATE)
        done = self.finish(pipeline)
        self.assertEqual((done.result, done.error), (ESTIMATE, None))
        self.assertEqual(pipeline.calls, [("https://sheet", "https://cd", None)])

    def test_error(self):
        done = self.finish(FakeEstimatePipeline(error=LarbError("sheet is private")))
        self.assertEqual(str(done.error), "sheet is private")

    def test_bug_still_ends(self):
        with mock.patch("traceback.print_exc"):
            done = self.finish(FakeEstimatePipeline(error=ValueError("oops")))
        self.assertIsInstance(done.error, LarbError)


class FakeEstimateWorker:
    """Answers at once with a prepared Done."""

    done = Done(ESTIMATE, None)
    created = []

    def __init__(self, store, request):
        self.queue = queue.Queue()
        self.request = request
        FakeEstimateWorker.created.append(self)

    def start(self):
        self.queue.put(LogEvent(Level.INFO, "sheet", "Reading song list: https://sheet"))
        self.queue.put(FakeEstimateWorker.done)

    def stop(self):
        pass


class WindowEstimateTest(unittest.TestCase):
    """The real window, with the worker replaced."""

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"no display: {e}")
        self.addCleanup(close_root, self.root)
        self.root.withdraw()
        self.dir = Path(tempfile.mkdtemp(prefix="test_", dir=ROOT / "workspace"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        store = TomlSettingsStore(self.dir / "config.toml", ROOT / "config" / "example.toml")
        self.window = window.Window(self.root, store, Settings(), mac=False,
                                    inputs_file=self.dir / "last_inputs.toml")
        self.popups = []
        self.window._popup = lambda title, message: self.popups.append((title, message))
        patcher = mock.patch.object(window, "EstimateWorker", FakeEstimateWorker)
        patcher.start()
        self.addCleanup(patcher.stop)
        FakeEstimateWorker.created.clear()

    def wait_for_popup(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not self.popups:
            self.root.update()

    def test_button_follows_the_sheet_field(self):
        self.assertFalse(self.window.est_length._enabled)
        self.window.sheet.set_value("https://sheet")
        self.assertTrue(self.window.est_length._enabled)
        self.window.sheet.set_value("   ")
        self.assertFalse(self.window.est_length._enabled)

    def test_popup_and_one_log_line(self):
        self.window.sheet.set_value("https://sheet")
        self.window.rows_from.insert(0, "3")
        self.window.est_length.invoke()
        self.assertIs(self.window.phase, Phase.ESTIMATING)
        self.assertFalse(self.window.run_button._enabled)
        self.wait_for_popup()
        self.assertEqual(self.popups, [("Est. Length", estimate_message(ESTIMATE))])
        log = self.window.log.get("1.0", "end").strip().splitlines()
        self.assertEqual(len(log), 1)   # the estimate's steps aren't logged, only its result
        self.assertIn("INFO", log[0])
        self.assertIn(estimate_log_line(ESTIMATE), log[0])
        self.assertIs(self.window.phase, Phase.IDLE)   # back to where it was
        self.assertTrue(self.window.run_button._enabled and self.window.est_length._enabled)
        self.assertEqual(FakeEstimateWorker.created[0].request.rows.first, 3)

    def test_failure_popup_and_error_line(self):
        FakeEstimateWorker.done = Done(None, LarbError("The sheet is private.\nShare it as Anyone with the link."))
        self.addCleanup(setattr, FakeEstimateWorker, "done", Done(ESTIMATE, None))
        self.window.sheet.set_value("https://sheet")
        self.window.est_length.invoke()
        self.wait_for_popup()
        self.assertEqual(self.popups[0][0], "Can't estimate")
        self.assertEqual(self.window.counts.errors, 1)
        self.assertIn("The sheet is private. Share it", self.window.log.get("1.0", "end"))

    def test_bad_rows_refused_before_starting(self):
        self.window.sheet.set_value("https://sheet")
        self.window.rows_from.insert(0, "x")
        self.window.est_length.invoke()
        self.assertEqual(self.popups[0][0], "Can't estimate")
        self.assertEqual(FakeEstimateWorker.created, [])

    def bar_sweeping(self) -> bool:
        return self.window.progress_bar._job is not None

    def test_progress_area_idle_again_before_any_run(self):
        """The bar used to keep sweeping after an estimate (maintainer report, 2026-10-02)."""
        self.window.sheet.set_value("https://sheet")
        self.window.est_length.invoke()
        self.assertTrue(self.bar_sweeping())   # "Estimating length"
        self.wait_for_popup()
        self.root.update()
        self.assertFalse(self.bar_sweeping())
        self.assertEqual(self.window.progress_bar.winfo_manager(), "")    # hidden, as before a run
        self.assertEqual(self.window.progress_label.winfo_manager(), "")

    def test_progress_area_shows_the_last_run_again(self):
        for error in (None, LarbError("The sheet is private.")):
            self.popups.clear()
            self.window.phase = Phase.FINISHED if error is None else Phase.FAILED
            self.window.progress.finish(error)
            self.window._show_progress(True)
            self.window._paint_progress()
            label = self.window.progress.text
            self.window.sheet.set_value("https://sheet")
            self.window.est_length.invoke()
            self.wait_for_popup()
            self.root.update()
            self.assertFalse(self.bar_sweeping())
            self.assertEqual(self.window.progress_label.cget("text"), label)   # "Finished" / "Stopped: ..."

    def test_closing_during_an_estimate(self):
        """Closes once the estimate has ended, remembering the fields; no pop-up."""
        class SlowWorker(FakeEstimateWorker):
            def start(self):
                pass   # answers only when stopped

            def stop(self):
                self.queue.put(Done(None, StoppedError("Stopped by the operator")))
        self.window.sheet.set_value("https://sheet")
        with mock.patch.object(window, "EstimateWorker", SlowWorker):
            self.window.est_length.invoke()
        self.window._on_close()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                self.root.update()
            except tk.TclError:   # destroyed: closed
                break
        self.assertRaises(tk.TclError, self.root.winfo_exists)
        self.assertEqual(self.popups, [])
        self.assertIn("https://sheet", (self.dir / "last_inputs.toml").read_text(encoding="utf-8"))

    def test_stopped_estimate_says_nothing(self):
        FakeEstimateWorker.done = Done(None, StoppedError("Stopped by the operator"))
        self.addCleanup(setattr, FakeEstimateWorker, "done", Done(ESTIMATE, None))
        self.window.sheet.set_value("https://sheet")
        self.window.est_length.invoke()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            self.root.update()
        self.assertEqual(self.popups, [])
        self.assertIs(self.window.phase, Phase.IDLE)


if __name__ == "__main__":
    unittest.main()
