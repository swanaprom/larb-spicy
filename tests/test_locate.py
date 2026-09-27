"""FFmpeg lookup: an FFmpeg older than 7.1 is refused with a clear message (offline)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from larb.adapters.ffmpeg import locate  # noqa: E402
from larb.core.errors import MediaToolMissingError  # noqa: E402


class LocateTest(unittest.TestCase):
    def test_old_system_ffmpeg_is_refused(self):
        with mock.patch.object(locate, "_static", side_effect=RuntimeError("fetch failed")), \
             mock.patch.object(locate.shutil, "which", side_effect=lambda n: f"C:/old/{n}.exe"), \
             mock.patch.object(locate, "_read_version", return_value=("4.4.2", (4, 4))):
            with self.assertRaises(MediaToolMissingError) as caught:
                locate.find_ffmpeg()
        message = str(caught.exception)
        self.assertIn("7.1 or newer", message)
        self.assertIn("system FFmpeg 4.4.2", message)
        self.assertIn("too old", message)

    def test_new_enough(self):
        self.assertFalse(locate._new_enough((7, 0)))
        self.assertTrue(locate._new_enough((7, 1)))
        self.assertTrue(locate._new_enough((8, 0)))
        self.assertTrue(locate._new_enough(None))   # dev builds: accepted, see locate.py


if __name__ == "__main__":
    unittest.main()
