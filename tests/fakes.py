"""Fakes and fixture paths shared by the offline tests (no sheet, no YouTube).

Not named test_*.py on purpose, so test discovery doesn't load it as a test module.
"""

import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from larb.adapters.ffmpeg.locate import find_ffmpeg  # noqa: E402
from larb.adapters.ffmpeg.processor import FfmpegProcessor  # noqa: E402
from larb.core.errors import DownloadError, MediaUnavailableError  # noqa: E402
from larb.core.models import MediaInfo, SheetRow  # noqa: E402
from larb.core.pipeline import Pipeline  # noqa: E402
from larb.core.ports import EventSink, MediaSource, SongListSource  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
XG = FIX / "XG - GRL GVNG (Instrumental).mp3"
SEWER = FIX / "sewer. [Instrumental].mp3"
THAI_MP4 = next(FIX.glob("*.mp4"))            # 7.27 s, awkward name on purpose
CD_MP3 = FIX / "countdown" / "!countdown.mp3"
CD_MP4 = FIX / "countdown" / "!countdown.mp4"


class FakeSongs(SongListSource):
    def __init__(self, rows):
        self.rows = rows

    def fetch_rows(self, source):
        return self.rows


class FakeMedia(MediaSource):
    """url -> (fixture file, reported length). Reported length can lie, like YouTube's rounding.

    Args:
        fail_first: urls whose first download fails with a retryable error.
        always_fail: urls whose downloads always fail with a retryable error.
    """

    def __init__(self, table, fail_first=(), always_fail=()):
        self.table = table
        self.downloads = 0
        self.lookups = 0
        self._fail_first = set(fail_first)
        self._always_fail = set(always_fail)

    def lookup(self, url):
        self.lookups += 1
        if url not in self.table:
            raise MediaUnavailableError(f"{url}: This video is unavailable")
        path, length = self.table[url]
        return MediaInfo(media_id=url.split("//")[-1], title=path.stem, duration_s=length)

    def download(self, url, kind, dest_dir, stem):
        if url in self._always_fail:
            raise DownloadError("HTTP Error 403: Forbidden", retryable=True)
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


class PipelineTestCase(unittest.TestCase):
    """Base for tests that run the real pipeline with the real FFmpeg processor,
    in a throwaway folder inside workspace/. Has no tests of its own."""

    @classmethod
    def setUpClass(cls):
        cls.tools = find_ffmpeg()

    def setUp(self):
        (ROOT / "workspace").mkdir(exist_ok=True)
        self.workspace = Path(tempfile.mkdtemp(prefix="test_", dir=ROOT / "workspace"))
        self.sink = RecordingSink()
        self.processor = FfmpegProcessor(self.tools, self.workspace / "tmp", self.sink)

    def tearDown(self):
        shutil.rmtree(self.workspace, ignore_errors=True)

    def real_length(self, path):
        return self.processor.measure(path, 0.0, 0.1).duration_s

    def run_pipeline(self, rows, media, countdown, settings, row_range=None):
        pipeline = Pipeline(FakeSongs(rows), media, self.processor, self.sink, self.workspace)
        return pipeline.run("fake-sheet", str(countdown), settings, rows=row_range,
                            now=datetime(2026, 9, 27, 14, 30, 12))
