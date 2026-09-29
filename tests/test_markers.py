"""Download started / ended markers and download progress (slice 5): structured data for
the GUI's active-download lines and progress label, never parsed from log text."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import SEWER, XG, FakeMedia, PipelineTestCase, row  # noqa: E402
from larb.core.models import DownloadSettings, Level, ProcessingSettings, Settings  # noqa: E402

SETTINGS = Settings(processing=ProcessingSettings(audio_only=True),
                    download=DownloadSettings(max_retries=1, max_parallel_downloads=2))


class MarkerTest(PipelineTestCase):
    def run_three(self):
        media = FakeMedia({"fx://ok": (XG, 189.0), "fx://flaky": (SEWER, 60.0), "fx://broken": (XG, 189.0),
                           "https://cd": (XG, 189.0)},
                          fail_first={"fx://flaky"}, always_fail={"fx://broken"})
        rows = [row(2, "fx://ok", "0:10-0:20", title="Perfect Night", artist="LE SSERAFIM"),
                row(3, "fx://flaky", "0:10-0:20", title="Drama", artist="เอสป้า"),
                row(4, "fx://broken", "0:10-0:20", title="Ditto", artist="")]
        return self.run_pipeline(rows, media, "https://cd", SETTINGS)

    def test_one_start_and_one_end_per_download(self):
        self.run_three()
        marks = [e for e in self.sink.events if e.activity]
        by_key = {}
        for e in marks:
            by_key.setdefault(e.activity.key, []).append(e.activity.started)
        # A retry (flaky) and a failure (broken) still give exactly one line each.
        self.assertEqual(by_key, {"cd_audio": [True, False], "ok_audio": [True, False],
                                  "flaky_audio": [True, False], "broken_audio": [True, False]})
        self.assertTrue(all(e.level is Level.DEBUG and e.stage == "download" for e in marks))
        labels = {e.activity.key: e.activity.label for e in marks}
        self.assertEqual(labels["ok_audio"], "Perfect Night - LE SSERAFIM")
        self.assertEqual(labels["flaky_audio"], "Drama - เอสป้า")
        self.assertEqual(labels["broken_audio"], "Ditto")
        self.assertTrue(labels["cd_audio"].startswith("countdown "))
        self.assertEqual({e.row_number for e in marks if e.activity.key == "ok_audio"}, {2})

    def test_download_and_measure_progress(self):
        self.run_three()
        downloads = [e.progress for e in self.sink.events if e.stage == "download" and e.progress]
        self.assertEqual(downloads[0], (0, 3))
        self.assertEqual(sorted(downloads[1:]), [(1, 3), (2, 3), (3, 3)])   # the failed one counts as done
        measures = [e.progress for e in self.sink.events if e.stage == "measure" and e.progress]
        self.assertEqual(measures, [(0, 2), (1, 2)])   # the two songs that downloaded
        # Progress-only events stay out of the console and the GUI's log (DEBUG); only the
        # "Downloading N video(s)" line that starts the stage is INFO.
        counted = [e for e in self.sink.events if e.progress and (e.stage == "measure" or
                                                                  e.stage == "download" and e.progress[0] > 0)]
        self.assertTrue(counted and all(e.level is Level.DEBUG for e in counted))


if __name__ == "__main__":
    unittest.main()
