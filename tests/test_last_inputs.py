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

from fakes import ROOT, close_root  # noqa: E402  (also puts src/ on the path)
from larb.adapters.toml_settings import TomlSettingsStore  # noqa: E402
from larb.core.cache import clear_cache  # noqa: E402
from larb.core.models import OutputSettings, Settings  # noqa: E402
from larb.gui import window  # noqa: E402
from larb.gui.memory import LastInputs, load_last_inputs, save_last_inputs  # noqa: E402

SHEET = "https://docs.google.com/spreadsheets/d/abc/edit"
COUNTDOWN = r"D:\เพลง\countdown.mp4"   # Thai in the path on purpose


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


class ClosingTest(unittest.TestCase):
    """Closing the window remembers the Sheet and Countdown fields as they are, without asking."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="test_", dir=ROOT / "workspace"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.file = self.dir / "last_inputs.toml"
        self.store = TomlSettingsStore(self.dir / "config.toml", ROOT / "config" / "example.toml")
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"no display: {e}")
        self.addCleanup(close_root, self.root)
        self.root.withdraw()
        settings = Settings(output=OutputSettings(directory=str(self.dir / "out")))
        self.win = window.Window(self.root, self.store, settings, mac=False, inputs_file=self.file)
        self.questions = []

    def close(self, answer=None):
        """Close the window; `answer` is what the operator picks if a question comes up."""
        def ask(_root, title, message, buttons, **_kwargs):
            self.questions.append(message)
            return answer
        with mock.patch.object(window, "ask", ask):
            self.win._on_close()

    def closed(self) -> bool:
        try:
            self.root.winfo_exists()
            return False
        except tk.TclError:
            return True

    def remembered(self) -> dict:
        return tomllib.loads(self.file.read_text(encoding="utf-8"))

    def test_edited_fields(self):
        save_last_inputs(self.file, LastInputs("https://old-sheet", "old.mp4"))
        self.win.sheet.set_value(SHEET)
        self.win.countdown.set_value(COUNTDOWN)
        self.win.rows_from.insert(0, "3")
        self.close()
        self.assertTrue(self.closed())
        self.assertEqual(self.questions, [])   # no question: only settings are asked about
        self.assertEqual(self.remembered(), {"sheet": SHEET, "countdown": COUNTDOWN})   # no row range

    def test_cleared_fields(self):
        save_last_inputs(self.file, LastInputs(SHEET, COUNTDOWN))
        self.win.sheet.set_value("")
        self.win.countdown.set_value("")
        self.close()
        self.assertEqual(self.remembered(), {"sheet": "", "countdown": ""})

    def test_save_from_the_close_question(self):
        self.win.sheet.set_value(SHEET)
        self.win._set_entry(self.win.crossfade, "2")   # an unsaved setting: the question comes up
        self.close(answer="save")
        self.assertEqual(self.questions, ["Save your changes?"])
        self.assertTrue(self.closed())
        self.assertEqual(self.remembered()["sheet"], SHEET)
        self.assertEqual(self.store.load().processing.crossfade_duration_seconds, 2.0)

    def test_dont_save_still_remembers_the_fields(self):
        self.win.sheet.set_value(SHEET)
        self.win._set_entry(self.win.crossfade, "2")
        self.close(answer="discard")
        self.assertEqual(self.remembered()["sheet"], SHEET)
        self.assertFalse((self.dir / "config.toml").exists())   # the settings weren't saved

    def test_cancel_keeps_the_window_and_remembers_nothing(self):
        self.win.sheet.set_value(SHEET)
        self.win._set_entry(self.win.crossfade, "2")
        self.close(answer="cancel")
        self.assertFalse(self.closed())
        self.assertFalse(self.file.exists())


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
        self.addCleanup(close_root, root)
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
