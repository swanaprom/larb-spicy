"""Smoke test: the whole pipeline, fully offline, from tests/fixtures/ only.

Fake song list and fake media source (no sheet fetch, no YouTube); the REAL
FFmpeg processor. Checks the output's length, not just that it exists: FFmpeg
can succeed and still write a wrong file (TECH §10).

Run from the repository root:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import math
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from larb.adapters.ffmpeg.locate import find_ffmpeg  # noqa: E402
from larb.adapters.ffmpeg.processor import FfmpegProcessor  # noqa: E402
from larb.core.errors import DownloadError, MediaUnavailableError  # noqa: E402
from larb.core.models import (DownloadSettings, Level, MediaInfo, ProcessingSettings,  # noqa: E402
                              Settings, SheetRow)
from larb.core.pipeline import Pipeline  # noqa: E402
from larb.core.ports import EventSink, MediaSource, SongListSource  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
XG = FIX / "XG - GRL GVNG (Instrumental).mp3"
SEWER = FIX / "sewer. [Instrumental].mp3"
THAI_MP4 = next(FIX.glob("*.mp4"))            # 7.27 s, awkward name on purpose
CD_MP3 = FIX / "countdown" / "!countdown.mp3"
CD_MP4 = FIX / "countdown" / "!countdown.mp4"
TOLERANCE_S = 0.1


class FakeSongs(SongListSource):
    def __init__(self, rows):
        self.rows = rows

    def fetch_rows(self, source):
        return self.rows


class FakeMedia(MediaSource):
    """url -> (fixture file, reported length). Reported length can lie, like YouTube's rounding."""

    def __init__(self, table, fail_first=()):
        self.table = table
        self.downloads = 0
        self._fail_first = set(fail_first)   # urls whose first download fails with a retryable error

    def lookup(self, url):
        if url not in self.table:
            raise MediaUnavailableError(f"{url}: This video is unavailable")
        path, length = self.table[url]
        return MediaInfo(media_id=url.split("//")[-1], title=path.stem, duration_s=length)

    def download(self, url, kind, dest_dir, stem):
        if url in self._fail_first:
            self._fail_first.discard(url)
            raise DownloadError("HTTP Error 403: Forbidden", retryable=True)
        self.downloads += 1
        path, _ = self.table[url]
        target = dest_dir / f"{stem}{path.suffix}"
        shutil.copyfile(path, target)
        return target


class RecordingSink(EventSink):
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def messages(self, level):
        return [f"{e.row_number}: {e.message}" for e in self.events if e.level is level]


def row(n, url, time_range, title="Song", artist="Artist", mirrored=""):
    return SheetRow(n, title, artist, url, time_range, mirrored)


class SmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools = find_ffmpeg()

    def setUp(self):
        (ROOT / "workspace").mkdir(exist_ok=True)
        self.workspace = Path(tempfile.mkdtemp(prefix="smoke_", dir=ROOT / "workspace"))
        self.sink = RecordingSink()
        self.processor = FfmpegProcessor(self.tools, self.workspace / "tmp", self.sink)

    def tearDown(self):
        shutil.rmtree(self.workspace, ignore_errors=True)

    def real_length(self, path):
        return self.processor.measure(path, 0.0, 0.1).duration_s

    def run_pipeline(self, rows, media, countdown, settings):
        pipeline = Pipeline(FakeSongs(rows), media, self.processor, self.sink, self.workspace)
        return pipeline.run("fake-sheet", countdown, settings, now=datetime(2026, 9, 27, 14, 30, 12))

    def test_audio_only(self):
        sewer_len = self.real_length(SEWER)                  # 66.51 s
        media = FakeMedia({
            "fx://xg": (XG, 189.0),
            "fx://sewer": (SEWER, math.ceil(sewer_len)),     # rounded up, like YouTube
            "fx://sewer-lying": (SEWER, 70.0),               # claims 70 s; real file is 66.5 s
        }, fail_first={"fx://xg"})
        rows = [
            row(2, "fx://xg", "0:30 - 0:40"),
            row(3, "fx://sewer", "0.1 0-0:20", artist=""),   # stray space; missing artist -> warning
            row(4, "fx://xg", "1.5-2:00"),                   # bad time -> row error
            row(5, "fx://sewer", "0:50-1:07"),               # 0.49 s past real end -> trim + warning
            row(6, "fx://sewer-lying", "1:00-1:09"),         # 2.5 s past real end -> row error
            row(7, "fx://missing", "0:10-0:20"),             # unavailable -> row error
        ]
        settings = Settings(processing=ProcessingSettings(audio_only=True, mirror=True),
                            download=DownloadSettings(max_parallel_downloads=2, max_retries=2))
        result = self.run_pipeline(rows, media, CD_MP3, settings)

        cd = self.real_length(CD_MP3)
        expected = 3 * cd + (41 - 29) + (21 - 9) + (sewer_len - 49) - 5 * 1.0
        self.assertEqual(result.output_path.name, "2026-09-27_143012.mp3")
        self.assertAlmostEqual(self.real_length(result.output_path), expected, delta=TOLERANCE_S)
        self.assertEqual(result.songs_rendered, 3)
        self.assertEqual(media.downloads, 3)   # xg + sewer + sewer-lying; sewer used twice = one download
        errors = " | ".join(self.sink.messages(Level.ERROR))
        warnings = " | ".join(self.sink.messages(Level.WARNING))
        for expected_error in ("4: skipped", "6: skipped: end", "7: skipped: video unavailable"):
            self.assertIn(expected_error, errors)
        for expected_warning in ("3: artist is empty", "5: end 67 s", "retry 1/2"):
            self.assertIn(expected_warning, warnings)

        # Same settings again: everything comes from the cache.
        media.downloads = 0
        again = self.run_pipeline(rows, media, CD_MP3, settings)
        self.assertEqual(media.downloads, 0)
        self.assertEqual(again.output_path.name, "2026-09-27_143012_2.mp3")   # never overwrites

    def test_video_mirror(self):
        media = FakeMedia({"fx://thai": (THAI_MP4, 8.0)})
        rows = [
            row(2, "fx://thai", "0:01-0:05"),                 # gets mirrored
            row(3, "fx://thai", "0:02-0:06", mirrored="1"),   # already mirrored: left as is
            row(4, "fx://thai", "0:03-0:07", mirrored="   "), # only spaces = not mirrored yet
        ]
        settings = Settings(processing=ProcessingSettings(audio_only=False, mirror=True),
                            download=DownloadSettings(max_height=360))
        result = self.run_pipeline(rows, media, CD_MP4, settings)

        cd, thai = self.real_length(CD_MP4), self.real_length(THAI_MP4)
        expected = 3 * cd + (6 - 0) + (7 - 1) + (min(thai, 8) - 2) - 5 * 1.0
        self.assertEqual(result.output_path.suffix, ".mp4")
        self.assertAlmostEqual(self.real_length(result.output_path), expected, delta=TOLERANCE_S)
        self.assertEqual(media.downloads, 1)                  # same video three times
        mirror_log = [e.message for e in self.sink.events if e.stage == "measure" and e.level is Level.DEBUG]
        self.assertEqual([m.endswith("mirror True") for m in mirror_log], [True, False, True])


if __name__ == "__main__":
    unittest.main()
