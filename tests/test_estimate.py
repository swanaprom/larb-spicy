"""Est. Length (slice 7, GUI.md 3.2): the output length a run would plan, without
looking up or downloading any song. Compared against the plan of a real run of the
same list (real FFmpeg, fake media source that counts its calls)."""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import (CD_MP3, CD_MP4, SEWER, THAI_MP4, XG, FakeMedia, FakeSongs,  # noqa: E402
                   PipelineTestCase, row)
from larb.core.errors import LarbError, RateLimitedError  # noqa: E402
from larb.core.manifest import (BAD_TIME_RANGE, CLIP_TOO_SHORT, END_PAST_END, START_PAST_END,  # noqa: E402
                                URL_EMPTY, RowProblem)
from larb.core.models import (DownloadSettings, ProcessingSettings, RowRange,  # noqa: E402
                              Settings)
from larb.core.pipeline import PADDING_S, Pipeline, song_clip  # noqa: E402

AUDIO = Settings(processing=ProcessingSettings(audio_only=True))
CD_URL = "https://cd"


class EstimateTest(PipelineTestCase):

    def setUp(self):
        super().setUp()
        self.plans = []
        render = self.processor.render

        def recording_render(plan, output_path):
            self.plans.append(plan)
            return render(plan, output_path)
        self.processor.render = recording_render

    def cache(self, source: Path, name: str) -> None:
        """Put a file in the cache under a cache name, e.g. "xg_audio.mp3"."""
        folder = self.workspace / "cache"
        folder.mkdir(exist_ok=True)
        shutil.copyfile(source, folder / name)

    def media(self, **kwargs):
        # YouTube-style lengths, rounded to whole seconds (an estimate must not use them).
        return FakeMedia({CD_URL: (CD_MP3, 5.0), "fx://xg": (XG, 50.0), "fx://sewer": (SEWER, 67.0),
                          "fx://thai": (THAI_MP4, 7.0)}, **kwargs)

    def estimate(self, rows, media, countdown=CD_URL, settings=AUDIO, row_range=None):
        pipeline = Pipeline(FakeSongs(rows), media, self.processor, self.sink, self.workspace)
        return pipeline.estimate("fake-sheet", str(countdown), settings, rows=row_range)

    def planned_length(self, rows, countdown=CD_URL, settings=AUDIO):
        """Run for real (fresh fake source) and return the length the run planned."""
        self.run_pipeline(rows, self.media(), countdown, settings)
        return self.plans[-1].expected_duration_s

    # -- accuracy ------------------------------------------------------------------

    def test_fully_cached_list_matches_the_plan(self):
        """Includes a trim-to-fit row, a skipped row, and a crossfade long enough that
        short clips shorten their joins: all of it is the run's own planning."""
        self.cache(CD_MP3, "cd_audio.mp3")
        self.cache(XG, "xg_audio.mp3")
        self.cache(SEWER, "sewer_audio.mp3")
        self.cache(THAI_MP4, "thai_audio.mp4")
        rows = [row(2, "fx://xg", "0:10-0:20"),
                row(3, "fx://sewer", "1:00-1:07"),     # 0.49 s past the end: trimmed
                row(4, "fx://sewer", "1:00-1:09"),     # 2.49 s past the end: skipped
                row(5, "fx://thai", "0:00-0:01")]      # 2 s clip: crossfades shortened
        settings = Settings(processing=ProcessingSettings(audio_only=True, crossfade_duration_seconds=2.0))
        media = self.media()
        estimate = self.estimate(rows, media, settings=settings)
        self.assertEqual((media.lookups, media.downloads), (0, 0))
        self.assertEqual((estimate.songs, estimate.from_cache), (3, 3))
        self.assertEqual(estimate.left_out, ((END_PAST_END, 1),))
        self.assertAlmostEqual(estimate.length_s, self.planned_length(rows, settings=settings), delta=0.05)

    def test_uncached_songs_within_a_second_each(self):
        """sewer's padded end (67 s) is past its real end (66.51 s): only a run can clamp it."""
        self.cache(CD_MP3, "cd_audio.mp3")
        rows = [row(2, "fx://xg", "0:10-0:20"), row(3, "fx://sewer", "1:00-1:06"),
                row(4, "fx://thai", "0:00-0:05")]
        media = self.media()
        estimate = self.estimate(rows, media)
        self.assertEqual((media.lookups, media.downloads), (0, 0))   # no YouTube at all
        self.assertEqual((estimate.songs, estimate.from_cache), (3, 0))
        self.assertAlmostEqual(estimate.length_s, self.planned_length(rows), delta=1.0 * len(rows))

    def test_mixed_cached_and_uncached(self):
        self.cache(CD_MP3, "cd_audio.mp3")
        self.cache(SEWER, "sewer_audio.mp3")
        rows = [row(2, "fx://xg", "0:10-0:20"), row(3, "fx://sewer", "0:30-0:40")]
        media = self.media()
        estimate = self.estimate(rows, media)
        self.assertEqual(media.lookups, 0)
        self.assertEqual(estimate.from_cache, 1)
        self.assertAlmostEqual(estimate.length_s, self.planned_length(rows), delta=1.0)

    def test_video_mode_measures_its_own_cache(self):
        self.cache(CD_MP4, "cd_v360.mp4")
        self.cache(THAI_MP4, "thai_v360.mp4")
        self.cache(XG, "xg_audio.mp3")    # an audio file: no use for a video estimate
        settings = Settings(processing=ProcessingSettings(audio_only=False),
                            download=DownloadSettings(max_height=360))
        media = self.media()
        estimate = self.estimate([row(2, "fx://thai", "0:01-0:05"), row(3, "fx://xg", "0:10-0:20")],
                                 media, settings=settings)
        self.assertEqual(media.lookups, 0)
        self.assertEqual((estimate.songs, estimate.from_cache), (2, 1))

    # -- the countdown ---------------------------------------------------------------

    def test_uncached_countdown_is_fetched_once_and_cached_for_the_run(self):
        rows = [row(2, "fx://xg", "0:10-0:20")]
        media = self.media()
        estimate = self.estimate(rows, media)
        self.assertEqual((media.lookup_urls, media.download_urls), ([CD_URL], [CD_URL]))
        # Measured from the downloaded file, not YouTube's rounded 5 s.
        self.assertTrue((self.workspace / "cache" / "cd_audio.mp3").is_file())
        run_media = self.media()
        self.run_pipeline(rows, run_media, CD_URL, AUDIO)
        self.assertNotIn(CD_URL, run_media.lookup_urls)   # the run finds it cached
        self.assertAlmostEqual(estimate.length_s, self.plans[-1].expected_duration_s, delta=1.0)

    def test_countdown_download_retries_like_a_run(self):
        media = self.media(fail_first=[CD_URL])
        pipeline = Pipeline(FakeSongs([row(2, "fx://xg", "0:10-0:20")]), media, self.processor,
                            self.sink, self.workspace, wait=lambda _s: False)
        pipeline.estimate("fake-sheet", CD_URL, AUDIO)
        self.assertEqual(media.download_urls, [CD_URL, CD_URL])

    def test_rate_limited_countdown_stops_the_estimate(self):
        media = self.media(rate_limited_lookups=[CD_URL])
        with self.assertRaises(RateLimitedError) as caught:
            self.estimate([row(2, "fx://xg", "0:10-0:20")], media)
        self.assertIn("YouTube is limiting this connection", str(caught.exception))
        self.assertEqual(media.downloads, 0)

    def test_missing_countdown_file(self):
        with self.assertRaises(LarbError):
            self.estimate([row(2, "fx://xg", "0:10-0:20")], self.media(), countdown=self.workspace / "gone.mp3")

    # -- rows left out -----------------------------------------------------------------

    def test_left_out_rows_by_reason_in_sheet_order(self):
        self.cache(CD_MP3, "cd_audio.mp3")
        self.cache(SEWER, "sewer_audio.mp3")
        rows = [row(2, "fx://xg", "1.5-0:20"),          # bad time range
                row(3, "", "0:10-0:20"),                # no URL
                row(4, "fx://xg", "0:20-0:10"),         # backwards: also a bad time range
                row(5, "fx://sewer", "1:10-1:20"),      # starts past the cached song's end
                row(6, "fx://xg", "0:10-0:20")]
        estimate = self.estimate(rows, self.media())
        self.assertEqual(estimate.songs, 1)
        self.assertEqual(estimate.left_out, ((BAD_TIME_RANGE, 2), (URL_EMPTY, 1), (START_PAST_END, 1)))

    def test_no_usable_songs(self):
        self.cache(CD_MP3, "cd_audio.mp3")
        estimate = self.estimate([row(2, "fx://xg", "nope")], self.media())
        self.assertEqual((estimate.length_s, estimate.songs, estimate.left_out), (0.0, 0, ((BAD_TIME_RANGE, 1),)))

    def test_row_range_applies(self):
        self.cache(CD_MP3, "cd_audio.mp3")
        rows = [row(2, "fx://xg", "0:10-0:20"), row(3, "fx://xg", "0:10-0:20")]
        self.assertEqual(self.estimate(rows, self.media(), row_range=RowRange(3, 3)).songs, 1)
        with self.assertRaises(LarbError):
            self.estimate(rows, self.media(), row_range=RowRange(2, 9))


class SongClipTest(unittest.TestCase):
    """The clip rule shared by a run and the estimate."""

    def test_padding_unknown_length(self):
        self.assertEqual(song_clip(10, 20, None), (10 - PADDING_S, 20 + PADDING_S, 0.0))
        self.assertEqual(song_clip(0, 20, None)[0], 0.0)

    def test_clamped_and_trimmed(self):
        start, end, trimmed = song_clip(60, 67, 66.5)
        self.assertEqual((start, end), (59.0, 66.5))
        self.assertAlmostEqual(trimmed, 0.5)

    def test_reasons(self):
        for args, reason in (((70, 80, 66.5), START_PAST_END), ((60, 69, 66.5), END_PAST_END),
                             ((0, 1, 0.05), CLIP_TOO_SHORT)):
            with self.assertRaises(RowProblem) as caught:
                song_clip(*args)
            self.assertEqual(caught.exception.reason, reason)


if __name__ == "__main__":
    unittest.main()
