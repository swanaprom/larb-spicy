"""Per-run log file: rotation keeps the newest 5, and every event (DEBUG too) is written."""

import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import ROOT  # noqa: E402  (also puts src/ on the path)
from larb.adapters.file_events import KEEP_LOGS, FileEventSink, prune_logs  # noqa: E402
from larb.core.models import Level, LogEvent  # noqa: E402

# Eight old logs, deliberately not created in age order. Oldest -> newest by name:
OLD_LOGS = ["2026-09-01_090000.log", "2026-09-01_090000_2.log", "2026-09-02_080000.log",
            "2026-09-10_235959.log", "2026-09-11_000000.log", "2026-09-20_120000.log",
            "2026-09-20_120000_2.log", "2026-09-21_070000.log"]


class LogRotationTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "workspace").mkdir(exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix="test_logs_", dir=ROOT / "workspace"))
        for name in reversed(OLD_LOGS):
            (self.dir / name).write_text("old", encoding="utf-8")
        (self.dir / "notes.txt").write_text("not a log", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def logs(self):
        return sorted(p.name for p in self.dir.glob("*.log"))

    def test_prune_keeps_exactly_the_newest(self):
        deleted = prune_logs(self.dir, 5)
        self.assertEqual(self.logs(), OLD_LOGS[-5:])
        self.assertEqual(sorted(p.name for p in deleted), OLD_LOGS[:3])
        self.assertTrue((self.dir / "notes.txt").exists())    # not a log: left alone

    def test_run_start_keeps_5_including_its_own(self):
        sink = FileEventSink(self.dir, datetime(2026, 9, 27, 14, 30, 12))
        sink.emit(LogEvent(Level.DEBUG, "ffmpeg", "ffmpeg -i x.mp4"))
        sink.emit(LogEvent(Level.WARNING, "manifest", "artist is empty", row_number=3))
        sink.close()
        self.assertEqual(KEEP_LOGS, 5)
        self.assertEqual(self.logs(), OLD_LOGS[-4:] + ["2026-09-27_143012.log"])
        text = sink.path.read_text(encoding="utf-8")
        self.assertIn("DEBUG   ffmpeg    ffmpeg -i x.mp4", text)   # DEBUG always goes to the file
        self.assertIn("row 3: artist is empty", text)

    def test_same_second_gets_a_new_name(self):
        first = FileEventSink(self.dir, datetime(2026, 9, 27, 14, 30, 12))
        second = FileEventSink(self.dir, datetime(2026, 9, 27, 14, 30, 12))
        first.close()
        second.close()
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(len(self.logs()), 5)


if __name__ == "__main__":
    unittest.main()
