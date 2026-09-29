"""Countdown from a URL (offline: the "URL" is served by the fake media source)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import CD_MP3, XG, FakeMedia, PipelineTestCase, row  # noqa: E402
from larb.core.errors import LarbError  # noqa: E402
from larb.core.models import (CountdownSettings, DownloadSettings, ProcessingSettings,  # noqa: E402
                              Settings)
from larb.core.pipeline import choose_countdown  # noqa: E402

CD_URL = "https://fx//countdown"     # is_url() -> True; FakeMedia's media ID is "countdown"
ROWS = [row(2, "fx://xg", "0:30-0:40")]
AUDIO = Settings(processing=ProcessingSettings(audio_only=True, crossfade_duration_seconds=1.0),
                 download=DownloadSettings(max_retries=2))


class ChooseCountdownTest(unittest.TestCase):
    def test_order(self):
        both = Settings(countdown=CountdownSettings(default_urls=("https://u1", "https://u2"),
                                                    default_files=("f1.mp4",)))
        files_only = Settings(countdown=CountdownSettings(default_files=("f1.mp4", "f2.mp4")))
        self.assertEqual(choose_countdown("given.mp4", both), "given.mp4")
        self.assertEqual(choose_countdown(None, both), "https://u1")      # default_urls first
        self.assertEqual(choose_countdown(None, files_only), "f1.mp4")    # then default_files

    def test_none_set(self):
        with self.assertRaisesRegex(LarbError, "No countdown"):
            choose_countdown(None, Settings())


class CountdownUrlTest(PipelineTestCase):
    def media(self, **kwargs):
        return FakeMedia({CD_URL: (CD_MP3, 7.0), "fx://xg": (XG, 189.0)}, **kwargs)

    def test_downloaded_cached_and_normalized(self):
        media = self.media(fail_first={CD_URL})              # also takes the retry path
        result = self.run_pipeline(ROWS, media, CD_URL, AUDIO)
        self.assertEqual(media.downloads, 2)                  # countdown + song
        self.assertTrue((result.cache_dir / "countdown_audio.mp3").is_file())   # same cache name rule
        expected = self.real_length(CD_MP3) + (41 - 29) - 1.0
        self.assertAlmostEqual(self.real_length(result.output_path), expected, delta=0.1)
        gain = [e.message for e in self.sink.events if e.stage == "countdown" and "gain" in e.message]
        self.assertTrue(gain and "gain +0.0 dB" not in gain[0], "countdown should be peak-normalized")

        media.downloads = 0                                   # second identical run
        self.run_pipeline(ROWS, media, CD_URL, AUDIO)
        self.assertEqual(media.downloads, 0)

    def test_unavailable_aborts_before_manifest(self):
        media = FakeMedia({"fx://xg": (XG, 189.0)})           # countdown URL unknown
        with self.assertRaisesRegex(LarbError, "Countdown video unavailable"):
            self.run_pipeline(ROWS, media, CD_URL, AUDIO)
        self.assertEqual(media.lookups, 1)                    # only the countdown: songs never looked up

    def test_download_failing_after_retries_aborts(self):
        media = self.media(always_fail={CD_URL})
        with self.assertRaisesRegex(LarbError, "Countdown download failed"):
            self.run_pipeline(ROWS, media, CD_URL, AUDIO)
        self.assertEqual(media.downloads, 0)
        retries = [e for e in self.sink.events if e.message.startswith("retry")]
        self.assertEqual(len(retries), 2)                     # same retry policy as songs


if __name__ == "__main__":
    unittest.main()
