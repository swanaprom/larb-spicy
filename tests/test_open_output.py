"""Open file / Open folder failing (slice 6, GUI.md 2.4): a pop-up with the reason, and
a warning in the log. The missing app is simulated; nothing is really opened."""

import shutil
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import ROOT  # noqa: E402  (also puts src/ on the path)
from larb.adapters.toml_settings import TomlSettingsStore  # noqa: E402
from larb.core.models import Settings  # noqa: E402
from larb.gui import opening, window  # noqa: E402
from larb.gui.opening import OpenAttempt  # noqa: E402
from larb.gui.state import open_failure_message  # noqa: E402

NO_APP_WINDOWS = "No application is associated with the specified file for this operation"
NO_APP_LINUX = "xdg-open: no method available for opening '/tmp/out.mp4'"


class FakeProcess:
    """What xdg-open looks like when no app is set for the file."""

    def __init__(self, args, **_kwargs):
        self.args = args
        self.returncode = None

    def communicate(self, timeout=None):
        self.returncode = 3
        return "", f"{NO_APP_LINUX}\n"


class OpenerTest(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="test_", dir=ROOT / "workspace"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.output = self.dir / "out.mp4"
        self.output.write_bytes(b"x")

    def finished(self, attempt):
        self.assertTrue(attempt.done.wait(5))
        return attempt.error

    def test_windows_without_an_app(self):
        error = OSError(22, NO_APP_WINDOWS)
        with mock.patch.object(opening.sys, "platform", "win32"), \
                mock.patch.object(opening.os, "startfile", side_effect=error, create=True):
            self.assertEqual(self.finished(opening.start_open(self.output)), NO_APP_WINDOWS)

    def test_linux_without_an_app(self):
        with mock.patch.object(opening.sys, "platform", "linux"), \
                mock.patch.object(opening.subprocess, "Popen", FakeProcess):
            self.assertEqual(self.finished(opening.start_open(self.output)), NO_APP_LINUX)

    def test_linux_opener_missing(self):
        with mock.patch.object(opening.sys, "platform", "linux"), \
                mock.patch.object(opening.subprocess, "Popen", side_effect=FileNotFoundError(2, "not found")):
            self.assertIn("xdg-open", self.finished(opening.start_open(self.output)))

    def test_linux_opener_still_running_is_success(self):
        class StillShowing(FakeProcess):
            def communicate(self, timeout=None):
                raise subprocess.TimeoutExpired(self.args, timeout)
        with mock.patch.object(opening.sys, "platform", "linux"), \
                mock.patch.object(opening.subprocess, "Popen", StillShowing):
            self.assertIsNone(self.finished(opening.start_open(self.output)))

    def test_messages(self):
        self.assertEqual(open_failure_message(self.output, False, "no player").splitlines()[0],
                         "No app is set to open .mp4 files. Install a media player, or use Open folder.")
        self.assertIn(str(self.dir), open_failure_message(self.dir, True, "no file manager"))
        self.assertIn("isn't there any more", open_failure_message(self.dir / "gone.mp4", False, "x"))


class WindowOpenFailureTest(unittest.TestCase):
    """The real window: a failed Open file shows the pop-up and logs a warning."""

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"no display: {e}")
        self.addCleanup(self.root.destroy)
        self.root.withdraw()
        self.dir = Path(tempfile.mkdtemp(prefix="test_", dir=ROOT / "workspace"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        store = TomlSettingsStore(self.dir / "config.toml", ROOT / "config" / "example.toml")
        self.window = window.Window(self.root, store, Settings(), mac=False)
        self.window.output_path = self.dir / "out.mp4"
        self.window.output_path.write_bytes(b"x")
        self.popups = []
        self.window._popup = lambda title, message: self.popups.append((title, message))

    def click(self, button, error):
        attempt = OpenAttempt(error=error)
        attempt.done.set()
        with mock.patch.object(window, "start_open", return_value=attempt):
            button()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not self.popups and error:
            self.root.update()

    def test_open_file_failure(self):
        self.click(self.window._open_file, NO_APP_WINDOWS)
        self.assertEqual(len(self.popups), 1)
        title, message = self.popups[0]
        self.assertEqual(title, "Open file")
        self.assertTrue(message.startswith("No app is set to open .mp4 files."), msg=message)
        self.assertEqual(self.window.counts.warnings, 1)
        log = self.window.log.get("1.0", "end")
        self.assertIn("WARNING", log)
        self.assertIn("No app is set to open .mp4 files", log)

    def test_open_folder_failure(self):
        self.click(self.window._open_folder, "no file manager")
        self.assertEqual(self.popups[0][0], "Open folder")
        self.assertEqual(self.window.counts.warnings, 1)

    def test_success_says_nothing(self):
        self.click(self.window._open_file, None)
        self.root.update()
        self.assertEqual((self.popups, self.window.counts.warnings), ([], 0))


if __name__ == "__main__":
    unittest.main()
