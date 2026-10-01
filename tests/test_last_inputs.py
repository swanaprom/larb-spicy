"""Remembered inputs (slice 7, GUI.md 1.1, 1.4): the Sheet and Countdown fields are
saved when Run is pressed and filled in when the window opens. Never the row range."""

import queue
import shutil
import sys
import tempfile
import tkinter as tk
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import ROOT  # noqa: E402  (also puts src/ on the path)
from larb.adapters.toml_settings import TomlSettingsStore  # noqa: E402
from larb.core.cache import clear_cache  # noqa: E402
from larb.core.models import Settings  # noqa: E402
from larb.gui import window  # noqa: E402
from larb.gui.memory import LastInputs, load_last_inputs, save_last_inputs  # noqa: E402

SHEET = "https://docs.google.com/spreadsheets/d/abc/edit"
COUNTDOWN = r"D:\เพลง\countdown.mp4"   # Thai in the path on purpose


def cancel_timers(root):
    """Cancel the window's pending timers, so they don't fire after it's destroyed."""
    for timer in root.tk.call("after", "info"):
        root.tk.call("after", "cancel", timer)   # not after_cancel: destroy() still owns the command


class MemoryFileTest(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="test_", dir=ROOT / "workspace"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.file = self.dir / "last_inputs.toml"

    def test_round_trip(self):
        self.assertIsNone(save_last_inputs(self.file, LastInputs(SHEET, COUNTDOWN)))
        self.assertEqual(load_last_inputs(self.file), LastInputs(SHEET, COUNTDOWN))

    def test_only_sheet_and_countdown_are_saved(self):
        save_last_inputs(self.file, LastInputs(SHEET, ""))
        self.assertEqual(set(tomllib.loads(self.file.read_text(encoding="utf-8"))), {"sheet", "countdown"})

    def test_missing_file(self):
        self.assertEqual(load_last_inputs(self.dir / "nothing.toml"), LastInputs())

    def test_corrupt_file(self):
        for content in (b"sheet = \"unclosed", b"\xff\xfe\x00garbage", b"sheet = 42\ncountdown = [1]"):
            self.file.write_bytes(content)
            self.assertEqual(load_last_inputs(self.file), LastInputs(), msg=content)

    def test_notepad_bom(self):
        self.file.write_bytes(f'sheet = "{SHEET}"\n'.encode("utf-8-sig"))
        self.assertEqual(load_last_inputs(self.file), LastInputs(SHEET, ""))

    def test_a_folder_in_the_way_is_reported_not_raised(self):
        self.file.mkdir()
        self.assertIsNotNone(save_last_inputs(self.file, LastInputs(SHEET, "")))

    def test_clear_cache_leaves_it_alone(self):
        """Even with the cache pointed at the same folder (clearing goes by name pattern)."""
        save_last_inputs(self.file, LastInputs(SHEET, COUNTDOWN))
        (self.dir / "abc_audio.m4a").write_bytes(b"x")
        self.assertEqual(clear_cache(self.dir), 1)
        self.assertEqual(load_last_inputs(self.file), LastInputs(SHEET, COUNTDOWN))


class IdleWorker:
    """Stands in for the run: never sends anything."""

    def __init__(self, store, request):
        self.queue = queue.Queue()

    def start(self):
        pass

    def stop(self):
        pass


class WindowMemoryTest(unittest.TestCase):
    """The real window."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="test_", dir=ROOT / "workspace"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.file = self.dir / "last_inputs.toml"
        self.store = TomlSettingsStore(self.dir / "config.toml", ROOT / "config" / "example.toml")
        self.settings = Settings()

    def open_window(self):
        try:
            root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"no display: {e}")
        self.addCleanup(root.destroy)
        self.addCleanup(cancel_timers, root)   # runs first: the window's timers die with it
        root.withdraw()
        # Output to the test folder, so a Run press doesn't touch workspace/output.
        self.settings = Settings(output=self.settings.output.__class__(directory=str(self.dir / "out")))
        win = window.Window(root, self.store, self.settings, mac=False, inputs_file=self.file)
        win._popup = lambda title, message: self.fail(f"pop-up: {title}: {message}")
        return win

    def test_filled_in_on_open(self):
        save_last_inputs(self.file, LastInputs(SHEET, COUNTDOWN))
        win = self.open_window()
        self.assertEqual((win.sheet.value(), win.countdown.value()), (SHEET, COUNTDOWN))
        self.assertEqual((win.rows_from.get(), win.rows_to.get()), ("", ""))
        self.assertTrue(win.est_length._enabled)

    def test_empty_on_open_without_a_file(self):
        win = self.open_window()
        self.assertEqual((win.sheet.value(), win.countdown.value()), ("", ""))
        self.assertFalse(win.est_length._enabled)

    def test_corrupt_file_opens_empty(self):
        self.file.write_text("this isn't = = toml", encoding="utf-8")
        win = self.open_window()
        self.assertEqual((win.sheet.value(), win.countdown.value()), ("", ""))

    def test_gone_countdown_file_is_still_filled_in(self):
        gone = str(self.dir / "deleted.mp4")
        save_last_inputs(self.file, LastInputs(SHEET, gone))
        self.assertEqual(self.open_window().countdown.value(), gone)

    def test_saved_on_run_without_rows(self):
        win = self.open_window()
        win.sheet.set_value(SHEET)
        win.countdown.set_value(COUNTDOWN)
        win.rows_from.insert(0, "3")
        win.rows_to.insert(0, "40")
        self.assertFalse(self.file.exists())   # not before Run
        with mock.patch.object(window, "RunWorker", IdleWorker):
            win.run_button.invoke()
        doc = tomllib.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual(doc, {"sheet": SHEET, "countdown": COUNTDOWN})   # no row range

    def test_not_saved_when_run_is_refused(self):
        win = self.open_window()
        win._popup = lambda title, message: None
        win.sheet.set_value(SHEET)
        win.rows_from.insert(0, "x")   # refused before the run starts
        with mock.patch.object(window, "RunWorker", IdleWorker):
            win.run_button.invoke()
        self.assertFalse(self.file.exists())


if __name__ == "__main__":
    unittest.main()
