"""Smarter retries (slice 6, SPEC §9 stage 5).

- A retryable failure (e.g. YouTube's occasional 403) waits longer before each retry, by
  a slightly random amount, so parallel retries don't arrive together.
- A rate limit (bot check / HTTP 429) is never retried: nothing new starts, running work
  ends, cached songs stay, and the run stops with a clear message.

The waits are recorded instead of waited (Pipeline's `wait` hook), with seeded randomness.
"""

import random
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import CD_MP3, SEWER, XG, FakeMedia, PipelineTestCase, row  # noqa: E402
from larb.core.errors import RateLimitedError  # noqa: E402
from larb.core.models import DownloadSettings, Level, ProcessingSettings, Settings  # noqa: E402
from larb.core.pipeline import (RATE_LIMITED_MESSAGE, RETRY_BASE_S, RETRY_JITTER,  # noqa: E402
                                retry_wait_s)


def settings(**download):
    return Settings(processing=ProcessingSettings(audio_only=True), download=DownloadSettings(**download))


class RecordedWaits:
    """Pipeline's wait hook: records each wait, never waits, never reports a stop."""

    def __init__(self):
        self.waits = []
        self._lock = threading.Lock()

    def __call__(self, seconds):
        with self._lock:
            self.waits.append(seconds)
        return False


class RetryWaitTest(unittest.TestCase):

    def test_waits_grow_and_stay_within_the_jitter(self):
        rng = random.Random(1)
        for _ in range(200):
            waits = [retry_wait_s(attempt, rng) for attempt in range(4)]
            for attempt, wait in enumerate(waits):
                base = RETRY_BASE_S * 2 ** attempt
                self.assertGreaterEqual(wait, base * (1 - RETRY_JITTER))
                self.assertLessEqual(wait, base * (1 + RETRY_JITTER))
            self.assertEqual(waits, sorted(waits), msg="each wait is longer than the one before")

    def test_waits_vary(self):
        rng = random.Random(2)
        first_waits = {round(retry_wait_s(0, rng), 3) for _ in range(20)}
        self.assertGreater(len(first_waits), 15)


class RetryPipelineTest(PipelineTestCase):

    def test_download_retries_wait_longer_each_time(self):
        media = FakeMedia({"fx://a": (XG, 189.0)}, always_fail={"fx://a"})
        waits = RecordedWaits()
        with self.assertRaises(Exception):   # the only song fails: nothing to render
            self.run_pipeline([row(2, "fx://a", "0:10-0:20")], media, CD_MP3, settings(max_retries=3),
                              rng=random.Random(3), wait=waits)
        self.assertEqual(len(waits.waits), 3)
        self.assertEqual(waits.waits, sorted(waits.waits))
        self.assertTrue(all(w > RETRY_BASE_S * (1 - RETRY_JITTER) - 1e-9 for w in waits.waits))

    def test_parallel_retries_dont_wait_alike(self):
        urls = [f"fx://s{n}" for n in range(4)]
        media = FakeMedia({url: (XG, 189.0) for url in urls}, fail_first=set(urls))
        waits = RecordedWaits()
        self.run_pipeline([row(n + 2, url, "0:10-0:20") for n, url in enumerate(urls)], media, CD_MP3,
                          settings(max_parallel_downloads=4), rng=random.Random(4), wait=waits)
        self.assertEqual(len(waits.waits), 4)                 # one retry each
        self.assertEqual(len(set(waits.waits)), 4)            # all different

    def test_lookup_retries_use_the_same_waits(self):
        media = FakeMedia({"fx://a": (XG, 189.0)}, lookup_fail_first={"fx://a"})
        waits = RecordedWaits()
        self.run_pipeline([row(2, "fx://a", "0:10-0:20")], media, CD_MP3, settings(),
                          rng=random.Random(5), wait=waits)
        self.assertEqual(len(waits.waits), 1)
        self.assertTrue([m for m in self.sink.messages(Level.WARNING) if "look-up retry 1/2 in" in m])


class RateLimitTest(PipelineTestCase):

    def assert_rate_limited(self, caught, cached, total):
        message = str(caught.exception)
        self.assertTrue(message.startswith(RATE_LIMITED_MESSAGE), msg=message)
        self.assertIn(f"{cached} of {total} song(s) are downloaded and cached", message)
        self.assertEqual(list((self.workspace / "output").iterdir()), [])   # nothing rendered

    def test_bot_check_during_lookups_starts_no_more(self):
        rows = [row(n + 2, f"fx://s{n}", "0:10-0:20") for n in range(5)]
        media = FakeMedia({f"fx://s{n}": (XG, 189.0) for n in range(5)}, rate_limited_lookups={"fx://s2"})
        with self.assertRaises(RateLimitedError) as caught:
            self.run_pipeline(rows, media, CD_MP3, settings(max_parallel_lookups=1))
        self.assertEqual(media.lookup_urls, ["fx://s0", "fx://s1", "fx://s2"])   # never retried, s3+ never asked
        self.assertEqual(media.downloads, 0)
        self.assert_rate_limited(caught, 0, 5)
        self.assertEqual(self.sink.messages(Level.ERROR), [])    # not reported as row errors

    def test_429_during_downloads_lets_running_ones_finish(self):
        """s0 is still downloading when s1 hits the limit: s0 finishes and stays cached,
        s2 never starts."""
        urls = ["fx://s0", "fx://s1", "fx://s2"]
        media = FakeMedia({url: (SEWER, 67.0) for url in urls}, rate_limited_downloads={"fx://s1"},
                          download_delays={"fx://s0": 0.5, "fx://s1": 0.1})
        with self.assertRaises(RateLimitedError) as caught:
            self.run_pipeline([row(n + 2, url, "0:10-0:20") for n, url in enumerate(urls)], media, CD_MP3,
                              settings(max_parallel_downloads=2))
        self.assertEqual(sorted(media.download_urls), ["fx://s0", "fx://s1"])
        self.assertEqual(sorted(p.name for p in (self.workspace / "cache").iterdir()), ["s0_audio.mp3"])
        self.assert_rate_limited(caught, 1, 3)
        warnings = [m for m in self.sink.messages(Level.WARNING) if "limiting this connection" in m]
        self.assertEqual(len(warnings), 1)

    def test_bot_check_on_the_countdown_stops_before_the_rows(self):
        media = FakeMedia({"https://cd": (CD_MP3, 6.0), "fx://a": (XG, 189.0)},
                          rate_limited_lookups={"https://cd"})
        with self.assertRaises(RateLimitedError) as caught:
            self.run_pipeline([row(2, "fx://a", "0:10-0:20")], media, "https://cd", settings())
        self.assertEqual(media.lookup_urls, ["https://cd"])
        self.assert_rate_limited(caught, 0, 1)


if __name__ == "__main__":
    unittest.main()
