"""The yt-dlp adapter looks each video up once and reuses that info to download (slice 2).

yt-dlp itself is replaced by a fake, so this runs offline: it checks which calls
the adapter makes, not what YouTube answers.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import ROOT, RecordingSink  # noqa: E402
from larb.adapters import ytdlp_media  # noqa: E402
from larb.core.errors import (DownloadError, MediaUnavailableError, RateLimitedError,  # noqa: E402
                              StoppedError)
from larb.core.models import Level, MediaKind  # noqa: E402

VIDEO = "https://www.youtube.com/watch?v=abcdefghijk"
WITH_LIST = VIDEO + "&list=RDMMabcdefghijk"
AUDIO = MediaKind(audio_only=True, max_height=720)


class FakeYoutubeDL:
    """Stands in for yt_dlp.YoutubeDL and records every call in `calls`."""

    calls: list[tuple] = []
    reuse_error: str | None = None      # process_ie_result raises this, if set
    lookup_error: str | None = None     # extract_info raises this, if set
    while_downloading = None            # called mid-download (e.g. the adapter's cancel), if set

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True, process=True, ie_key=None):
        FakeYoutubeDL.calls.append(("extract", url, download, process))
        if FakeYoutubeDL.lookup_error:
            raise ytdlp_media.yt_dlp.utils.DownloadError(FakeYoutubeDL.lookup_error)
        if "list=" in url:   # what YouTube's extractor answers with noplaylist
            return {"_type": "url", "url": VIDEO, "ie_key": "Youtube"}
        info = {"id": "abcdefghijk", "title": "Song", "duration": 100,
                "automatic_captions": {"en": ["big"]}, "formats": []}
        return self._fake_download(info) if download else info

    def process_ie_result(self, info, download=True):
        FakeYoutubeDL.calls.append(("reuse", info["id"]))
        if FakeYoutubeDL.reuse_error:
            raise ytdlp_media.yt_dlp.utils.DownloadError(FakeYoutubeDL.reuse_error)
        return self._fake_download(info)

    def _fake_download(self, info):
        path = Path(self.options["outtmpl"].replace("%(ext)s", "webm"))
        if FakeYoutubeDL.while_downloading:
            Path(f"{path}.part").write_bytes(b"half")
            FakeYoutubeDL.while_downloading()
            for hook in self.options.get("progress_hooks", []):   # yt-dlp calls these as data arrives
                hook({"status": "downloading"})
        path.write_bytes(b"fake")
        return {**info, "requested_downloads": [{"filepath": str(path)}]}


class YtDlpReuseTest(unittest.TestCase):

    def setUp(self):
        (ROOT / "workspace").mkdir(exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix="test_", dir=ROOT / "workspace"))
        FakeYoutubeDL.calls = []
        FakeYoutubeDL.reuse_error = None
        FakeYoutubeDL.lookup_error = None
        FakeYoutubeDL.while_downloading = None
        patcher = mock.patch.object(ytdlp_media.yt_dlp, "YoutubeDL", FakeYoutubeDL)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sink = RecordingSink()
        self.source = ytdlp_media.YtDlpMediaSource(Path("ffmpeg-dir"), self.sink)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def download(self, url=VIDEO):
        return self.source.download(url, AUDIO, self.dir, "abcdefghijk_audio")

    def fresh_lookups_logged(self):
        return [e.message for e in self.sink.events if e.level is Level.INFO and "looking it up again" in e.message]

    def test_download_reuses_the_lookup(self):
        info = self.source.lookup(VIDEO)
        self.assertEqual((info.media_id, info.duration_s), ("abcdefghijk", 100.0))
        path = self.download()
        self.assertTrue(path.is_file())
        self.assertEqual(FakeYoutubeDL.calls, [("extract", VIDEO, False, False), ("reuse", "abcdefghijk")])
        self.assertEqual(self.fresh_lookups_logged(), [])

    def test_lookup_follows_the_playlist_redirect_and_drops_captions(self):
        self.source.lookup(WITH_LIST)
        self.assertEqual(FakeYoutubeDL.calls, [("extract", WITH_LIST, False, False),
                                               ("extract", VIDEO, False, False)])
        remembered = self.source._remembered[WITH_LIST][1]
        self.assertNotIn("automatic_captions", remembered)
        self.download(WITH_LIST)
        self.assertEqual(FakeYoutubeDL.calls[-1], ("reuse", "abcdefghijk"))

    def test_remembered_info_is_used_only_once(self):
        self.source.lookup(VIDEO)
        self.download()
        self.download()     # e.g. a retry by the core: must fetch fresh info
        self.assertEqual(FakeYoutubeDL.calls[-1], ("extract", VIDEO, True, True))
        self.assertEqual(len(self.fresh_lookups_logged()), 1)

    def test_download_without_lookup_looks_up_fresh(self):
        self.download()
        self.assertEqual(FakeYoutubeDL.calls, [("extract", VIDEO, True, True)])
        self.assertEqual(len(self.fresh_lookups_logged()), 1)

    def test_failed_reuse_falls_back_to_a_fresh_lookup(self):
        self.source.lookup(VIDEO)
        FakeYoutubeDL.reuse_error = "ERROR: unable to download video data: HTTP Error 403: Forbidden"
        path = self.download()
        self.assertTrue(path.is_file())
        self.assertEqual(FakeYoutubeDL.calls[1:], [("reuse", "abcdefghijk"), ("extract", VIDEO, True, True)])
        self.assertEqual(len(self.fresh_lookups_logged()), 1)

    def test_permanent_failure_with_reused_info_is_not_repeated(self):
        self.source.lookup(VIDEO)
        FakeYoutubeDL.reuse_error = "ERROR: [youtube] abcdefghijk: Private video"
        with self.assertRaises(DownloadError) as caught:
            self.download()
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(FakeYoutubeDL.calls[-1], ("reuse", "abcdefghijk"))

    def test_old_info_is_not_reused(self):
        self.source.lookup(VIDEO)
        with mock.patch.object(ytdlp_media, "REMEMBER_FOR_S", -1):
            self.download()
        self.assertEqual(FakeYoutubeDL.calls[-1], ("extract", VIDEO, True, True))
        self.assertIn("min old", self.fresh_lookups_logged()[0])

    def test_lookup_errors_say_whether_to_retry(self):
        FakeYoutubeDL.lookup_error = "ERROR: [youtube] abcdefghijk: Video unavailable"
        with self.assertRaises(MediaUnavailableError) as caught:
            self.source.lookup(VIDEO)
        self.assertFalse(caught.exception.retryable)
        FakeYoutubeDL.lookup_error = "ERROR: Unable to download API page: timed out"
        with self.assertRaises(MediaUnavailableError) as caught:
            self.source.lookup(VIDEO)
        self.assertTrue(caught.exception.retryable)


class YtDlpLimitsTest(unittest.TestCase):
    """Slice 6: the bot check / HTTP 429 is never retried, and media_id needs no request."""

    setUp = YtDlpReuseTest.setUp
    tearDown = YtDlpReuseTest.tearDown
    download = YtDlpReuseTest.download

    def test_bot_check_and_429_are_rate_limits(self):
        for message in ("ERROR: [youtube] abcdefghijk: Sign in to confirm you're not a bot. Use "
                        "--cookies-from-browser or --cookies for the authentication.",
                        "ERROR: Unable to download webpage: HTTP Error 429: Too Many Requests"):
            FakeYoutubeDL.lookup_error = message
            with self.assertRaises(RateLimitedError):
                self.source.lookup(VIDEO)
            with self.assertRaises(RateLimitedError):
                self.download()   # no remembered info: the fresh look-up hits the same answer

    def test_rate_limit_with_reused_info_is_not_looked_up_again(self):
        self.source.lookup(VIDEO)
        FakeYoutubeDL.reuse_error = "ERROR: unable to download video data: HTTP Error 429: Too Many Requests"
        with self.assertRaises(RateLimitedError):
            self.download()
        self.assertEqual([c[0] for c in FakeYoutubeDL.calls], ["extract", "reuse"])

    def test_media_id_from_the_url_alone(self):
        for url in (VIDEO, WITH_LIST, "https://youtu.be/abcdefghijk?si=x1y2",
                    "https://music.youtube.com/watch?v=abcdefghijk&feature=share",
                    "https://www.youtube.com/shorts/abcdefghijk",
                    "https://www.youtube.com/watch?app=desktop&v=abcdefghijk"):
            self.assertEqual(self.source.media_id(url), "abcdefghijk", msg=url)
        for url in ("https://www.youtube.com/watch?v=abcdefg",           # truncated: look it up
                    "https://www.youtube.com/playlist?list=PL123", "https://example.com/a.mp4", "abc"):
            self.assertIsNone(self.source.media_id(url), msg=url)
        self.assertEqual(FakeYoutubeDL.calls, [])   # no request


class YtDlpCancelTest(unittest.TestCase):
    """cancel() (slice 5): downloads stop in yt-dlp's progress hook; later calls don't start."""

    setUp = YtDlpReuseTest.setUp
    tearDown = YtDlpReuseTest.tearDown

    def test_cancel_mid_download(self):
        self.source.lookup(VIDEO)
        FakeYoutubeDL.while_downloading = self.source.cancel
        with self.assertRaises(StoppedError):
            self.source.download(VIDEO, AUDIO, self.dir, "abcdefghijk_audio")
        # Not retried with a fresh look-up, and the partial file is left for the core to remove.
        self.assertEqual([c[0] for c in FakeYoutubeDL.calls], ["extract", "reuse"])
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["abcdefghijk_audio.webm.part"])

    def test_calls_after_cancel_start_nothing(self):
        self.source.cancel()
        with self.assertRaises(StoppedError):
            self.source.lookup(VIDEO)
        with self.assertRaises(StoppedError):
            self.source.download(VIDEO, AUDIO, self.dir, "abcdefghijk_audio")
        self.assertEqual(FakeYoutubeDL.calls, [])


if __name__ == "__main__":
    unittest.main()
