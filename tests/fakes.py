"""Fakes and fixture paths shared by the offline tests (no sheet, no YouTube).

Not named test_*.py on purpose, so test discovery doesn't load it as a test module.
"""

import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from larb.adapters.ffmpeg.locate import find_ffmpeg  # noqa: E402
from larb.adapters.ffmpeg.processor import FfmpegProcessor  # noqa: E402
from larb.core.errors import DownloadError, MediaUnavailableError, StoppedError  # noqa: E402
from larb.core.models import MediaInfo, SheetRow  # noqa: E402
from larb.core.pipeline import Pipeline  # noqa: E402
from larb.core.ports import EventSink, MediaSource, SongListSource  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
XG = FIX / "XG - GRL GVNG (Instrumental).mp3"
SEWER = FIX / "sewer. [Instrumental].mp3"
THAI_MP4 = next(FIX.glob("*.mp4"))            # 7.27 s, awkward name on purpose
CD_MP3 = FIX / "countdown" / "!countdown.mp3"
CD_MP4 = FIX / "countdown" / "!countdown.mp4"
CD_OPUS = FIX / "countdown" / "tone_3s.webm"    # Opus: container says 3.008 s, decodes to 3.000 s


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
        lookup_delays: url -> seconds its look-up takes (to make parallel look-ups
            finish out of sheet order).
        lookup_fail_first: urls whose first look-up fails with a retryable error.
        hang_until_cancel: urls whose download writes a partial file, then waits
            for cancel() and raises StoppedError (like an interrupted download).
    """

    def __init__(self, table, fail_first=(), always_fail=(), lookup_delays=None, lookup_fail_first=(),
                 hang_until_cancel=()):
        self.table = table
        self.downloads = 0
        self.lookups = 0
        self.max_concurrent_lookups = 0
        self._running_lookups = 0
        self._lock = threading.Lock()   # the pipeline looks up from several threads
        self._fail_first = set(fail_first)
        self._always_fail = set(always_fail)
        self._lookup_delays = lookup_delays or {}
        self._lookup_fail_first = set(lookup_fail_first)
        self._hang = set(hang_until_cancel)
        self.cancelled = threading.Event()
        self.download_started = threading.Event()   # set when any download begins
        self.lookup_urls = []                       # every url looked up, in call order

    def cancel(self):
        self.cancelled.set()

    def lookup(self, url):
        if self.cancelled.is_set():
            raise StoppedError("Stopped")
        with self._lock:
            self.lookups += 1
            self.lookup_urls.append(url)
            self._running_lookups += 1
            self.max_concurrent_lookups = max(self.max_concurrent_lookups, self._running_lookups)
            fail_now = url in self._lookup_fail_first
            self._lookup_fail_first.discard(url)
        try:
            time.sleep(self._lookup_delays.get(url, 0.0))
            if fail_now:
                raise MediaUnavailableError(f"{url}: connection reset", retryable=True)
            if url not in self.table:
                raise MediaUnavailableError(f"{url}: This video is unavailable")
            path, length = self.table[url]
            return MediaInfo(media_id=url.split("//")[-1], title=path.stem, duration_s=length)
        finally:
            with self._lock:
                self._running_lookups -= 1

    def download(self, url, kind, dest_dir, stem):
        if self.cancelled.is_set():
            raise StoppedError("Stopped")
        self.download_started.set()
        if url in self._hang:
            (dest_dir / f"{stem}.webm.part").write_bytes(b"half a song")
            if not self.cancelled.wait(10):   # never cancelled: fail differently, so a test notices
                raise DownloadError(f"{url}: never cancelled", retryable=False)
            raise StoppedError("Stopped")
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
