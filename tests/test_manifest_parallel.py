"""Manifest look-ups run in parallel, but results are reported in sheet order (slice 2).

The fake media source gives some look-ups a delay, so rows finish out of order,
and makes some rows fail, so we can check each error lands on the right row.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import CD_MP3, SEWER, XG, FakeMedia, PipelineTestCase, row  # noqa: E402
from larb.core.errors import LarbError  # noqa: E402
from larb.core.models import (CountdownSettings, DownloadSettings, Level,  # noqa: E402
                              ProcessingSettings, Settings)

TOLERANCE_S = 0.1


def settings(parallel=3):
    return Settings(processing=ProcessingSettings(audio_only=True),
                    download=DownloadSettings(max_parallel_lookups=parallel, max_retries=2))


# Rows 2 and 4 are slow, so rows after them finish first.
MEDIA_TABLE = {"fx://a": (XG, 189.0), "fx://b": (SEWER, 67.0), "fx://c": (XG, 189.0),
               "fx://d": (SEWER, 67.0), "fx://e": (XG, 189.0)}
DELAYS = {"fx://a": 0.4, "fx://b": 0.05, "fx://c": 0.3, "fx://missing": 0.1, "fx://e": 0.02}
ROWS = [
    row(2, "fx://a", "0:10-0:14"),                  # ok, slowest
    row(3, "fx://b", "1.5-0:20"),                   # bad time range (offline)
    row(4, "fx://c", "0:20-0:24", artist=""),       # ok, with a warning
    row(5, "fx://missing", "0:10-0:14"),            # video unavailable
    row(6, "fx://b", "1:00-1:30"),                  # end past the video's length
    row(7, "fx://d", "0:05-0:09"),                  # first look-up fails, the retry works
    row(8, "fx://e", "0:30-0:34"),                  # ok, fast
]


class ParallelManifestTest(PipelineTestCase):

    def manifest_events(self):
        """Per-row manifest messages (not progress), in the order they were reported."""
        return [e for e in self.sink.events
                if e.stage == "manifest" and e.row_number is not None and e.progress is None]

    def progress_events(self):
        return [e for e in self.sink.events if e.stage == "manifest" and e.progress is not None]

    def test_results_in_sheet_order_with_the_right_row_errors(self):
        media = FakeMedia(MEDIA_TABLE, lookup_delays=DELAYS, lookup_fail_first={"fx://d"})
        result = self.run_pipeline(ROWS, media, CD_MP3, settings())

        # Reported in sheet order...
        reported = [e.row_number for e in self.manifest_events()]
        self.assertEqual(reported, sorted(reported))
        # ...although they finished in another order (else this test proves nothing).
        finished = [e.row_number for e in self.progress_events() if e.progress[0] > 0]
        self.assertNotEqual(finished, sorted(finished), "rows should finish out of sheet order")
        self.assertGreater(media.max_concurrent_lookups, 1)
        self.assertLessEqual(media.max_concurrent_lookups, 3)

        def said(level, row_number):
            return " | ".join(e.message for e in self.manifest_events()
                              if e.level is level and e.row_number == row_number)

        self.assertIn("ok:", said(Level.INFO, 2))
        self.assertIn("time range", said(Level.ERROR, 3))
        self.assertIn("artist is empty", said(Level.WARNING, 4))
        self.assertIn("ok:", said(Level.INFO, 4))
        self.assertIn("video unavailable", said(Level.ERROR, 5))
        self.assertIn("past the video's length", said(Level.ERROR, 6))
        self.assertIn("look-up retry 1/2", said(Level.WARNING, 7))
        self.assertIn("ok:", said(Level.INFO, 7))
        self.assertIn("ok:", said(Level.INFO, 8))
        errored = {e.row_number for e in self.manifest_events() if e.level is Level.ERROR}
        self.assertEqual(errored, {3, 5, 6})

        # The usable rows render, in sheet order, to the planned length.
        self.assertEqual(result.songs_rendered, 4)
        self.assertEqual(result.row_errors, 3)
        cd = self.real_length(CD_MP3)
        clip = 4.0 + 2 * 1.0                    # 4 s range + 1 s padding each side
        expected = 4 * (cd + clip) - 7 * 1.0    # 8 segments, 7 crossfades
        self.assertAlmostEqual(self.real_length(result.output_path), expected, delta=TOLERANCE_S)

    def test_one_progress_event_per_row(self):
        media = FakeMedia(MEDIA_TABLE, lookup_delays=DELAYS)
        self.run_pipeline(ROWS, media, CD_MP3, settings())
        progress = [e.progress for e in self.progress_events()]
        total = len(ROWS)
        # One "starting" event, then one per row (offline-rejected rows included), counting up.
        self.assertEqual(progress, [(n, total) for n in range(total + 1)])
        rows_with_progress = sorted(e.row_number for e in self.progress_events() if e.progress[0] > 0)
        self.assertEqual(rows_with_progress, [r.row_number for r in ROWS])

    def test_permanent_lookup_error_is_not_retried(self):
        media = FakeMedia(MEDIA_TABLE)
        self.run_pipeline([row(2, "fx://a", "0:10-0:14"), row(3, "fx://missing", "0:10-0:14")],
                          media, CD_MP3, settings())
        self.assertEqual(media.lookups, 2)   # one each; "unavailable" isn't worth a retry

    def test_retryable_lookup_error_gives_up_after_max_retries(self):
        media = FakeMedia(MEDIA_TABLE)
        media.lookup = self.always_failing(media.lookup, "fx://b")
        self.run_pipeline([row(2, "fx://a", "0:10-0:14"), row(3, "fx://b", "0:10-0:14")],
                          media, CD_MP3, settings())
        warnings = [e.message for e in self.manifest_events() if e.level is Level.WARNING and e.row_number == 3]
        self.assertEqual(len(warnings), 2)   # retry 1/2 and 2/2, then a row error
        errors = [e.message for e in self.manifest_events() if e.level is Level.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertIn("video unavailable", errors[0])

    def test_one_at_a_time(self):
        media = FakeMedia(MEDIA_TABLE, lookup_delays=DELAYS)
        self.run_pipeline(ROWS, media, CD_MP3, settings(parallel=1))
        self.assertEqual(media.max_concurrent_lookups, 1)
        finished = [e.row_number for e in self.progress_events() if e.progress[0] > 0]
        self.assertEqual(finished, sorted(finished))

    def test_lookups_use_their_own_limit(self):
        media = FakeMedia(MEDIA_TABLE, lookup_delays=DELAYS)
        s = Settings(processing=ProcessingSettings(audio_only=True),
                     download=DownloadSettings(max_parallel_downloads=1, max_parallel_lookups=4))
        self.run_pipeline(ROWS, media, CD_MP3, s)
        self.assertGreater(media.max_concurrent_lookups, 1)   # not held to max_parallel_downloads
        self.assertLessEqual(media.max_concurrent_lookups, 4)

    def test_countdown_lookup_is_retried(self):
        media = FakeMedia({**MEDIA_TABLE, "https://cd": (CD_MP3, 6.0)}, lookup_fail_first={"https://cd"})
        s = Settings(processing=ProcessingSettings(audio_only=True),
                     countdown=CountdownSettings(default_urls=("https://cd",)))
        result = self.run_pipeline([row(2, "fx://a", "0:10-0:14")], media, "https://cd", s)
        self.assertEqual(result.songs_rendered, 1)
        retries = [e.message for e in self.sink.events if e.stage == "countdown" and e.level is Level.WARNING
                   and "retry" in e.message]
        self.assertEqual(len(retries), 1)

    def test_countdown_lookup_failing_after_retries_aborts(self):
        media = FakeMedia(MEDIA_TABLE)
        media.lookup = self.always_failing(media.lookup, "https://cd")
        with self.assertRaisesRegex(LarbError, "Countdown video unavailable"):
            self.run_pipeline([row(2, "fx://a", "0:10-0:14")], media, "https://cd", settings())

    @staticmethod
    def always_failing(lookup, bad_url):
        """Wrap a look-up so bad_url always fails with a retryable error."""
        from larb.core.errors import MediaUnavailableError

        def wrapped(url):
            if url == bad_url:
                raise MediaUnavailableError(f"{url}: connection reset", retryable=True)
            return lookup(url)
        return wrapped


if __name__ == "__main__":
    unittest.main()
