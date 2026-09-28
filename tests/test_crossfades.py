"""Crossfade per join (slice 3): a join's crossfade is the setting, or the longest
both clips next to it can hold without their fades overlapping, whichever is smaller.

A clip keeps at least one frame to itself: its length minus one frame, halved when
it has a fade on both sides (the end fade-out counts as a fade). A shortened join
gets a warning: once per run for the countdown, per row for a song.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import CD_MP3, CD_MP4, SEWER, THAI_MP4, FakeMedia, PipelineTestCase, row  # noqa: E402
from larb.core.errors import LarbError  # noqa: E402
from larb.core.models import ClipInfo, DownloadSettings, Level, ProcessingSettings, Settings  # noqa: E402
from larb.core.pipeline import FRAME_S, crossfade_limits, plan_crossfades  # noqa: E402

TOLERANCE_S = 0.1


class PlanCrossfadesTest(unittest.TestCase):

    def test_short_clips_shorten_their_joins(self):
        # countdown 5, song 10, countdown 5, song 3 (last: crossfade in + end fade-out)
        joins, fade = plan_crossfades([5.0, 10.0, 5.0, 3.0], 2.0)
        short = (3.0 - FRAME_S) / 2
        self.assertEqual(joins[:2], (2.0, 2.0))
        self.assertAlmostEqual(joins[2], short)
        self.assertAlmostEqual(fade, short)

    def test_first_clip_has_one_side_and_the_last_has_two(self):
        self.assertEqual(crossfade_limits([3.0, 3.0], fade_out=True), [3.0 - FRAME_S, (3.0 - FRAME_S) / 2])
        self.assertEqual(crossfade_limits([3.0, 3.0], fade_out=False), [3.0 - FRAME_S, 3.0 - FRAME_S])

    def test_setting_used_when_everything_is_long_enough(self):
        self.assertEqual(plan_crossfades([5.3, 12.0, 5.3, 12.0], 1.0), ((1.0, 1.0, 1.0), 1.0))

    def test_no_clip_ever_has_overlapping_fades(self):
        durations = [5.3, 0.9, 5.3, 40.0, 1.2, 0.2, 5.3, 2.0]
        for setting in (0.5, 1.0, 3.0, 10.0):
            joins, fade = plan_crossfades(durations, setting)
            fades_in = (0.0, *joins)
            fades_out = (*joins, fade)
            for length, f_in, f_out in zip(durations, fades_in, fades_out):
                self.assertLessEqual(f_in + f_out, length - FRAME_S + 1e-9)
                self.assertGreater(f_out, 0)


class ShortClipsRenderTest(PipelineTestCase):

    def test_short_countdown(self):
        """Countdown 5.33 s with a 4 s crossfade: every join next to a middle countdown
        is shortened; one warning for the whole run."""
        media = FakeMedia({"fx://sewer": (SEWER, 67.0)})
        rows = [row(2, "fx://sewer", "0:10-0:20"), row(3, "fx://sewer", "0:30-0:40")]   # 12 s clips
        settings = Settings(processing=ProcessingSettings(audio_only=True, crossfade_duration_seconds=4.0))
        result = self.run_pipeline(rows, media, CD_MP3, settings)

        cd = self.real_length(CD_MP3)
        short = (cd - FRAME_S) / 2                          # ~2.65 s
        # joins: countdown(first, one side)->song = 4; song->countdown and countdown->song = short;
        # end fade-out on a 12 s song = 4 (no length).
        expected = 2 * cd + 2 * 12.0 - (4.0 + short + short)
        self.assertAlmostEqual(self.real_length(result.output_path), expected, delta=TOLERANCE_S)
        warnings = [m for m in self.sink.messages(Level.WARNING) if "shortened" in m]
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn(f"Countdown is only {cd:.2f} s: crossfades next to it shortened to {short:.2f} s", warnings[0])

    def test_short_song(self):
        """A 3 s clip (0:00-0:02 plus padding) with a 2 s crossfade, in video mode: its
        joins are shortened, with a row warning; the next song is long enough."""
        media = FakeMedia({"fx://thai": (THAI_MP4, 8.0)})
        rows = [row(2, "fx://thai", "0:00-0:02", title="Short"),   # clip 0-3 s
                row(3, "fx://thai", "0:02-0:05")]                   # clip 1-6 s, last (fade-out too)
        settings = Settings(processing=ProcessingSettings(audio_only=False, crossfade_duration_seconds=2.0),
                            download=DownloadSettings(max_height=360))
        result = self.run_pipeline(rows, media, CD_MP4, settings)

        cd = self.real_length(CD_MP4)
        short = (3.0 - FRAME_S) / 2                          # ~1.48 s
        # the last song (5 s, two sides) holds (5 - 1 frame) / 2 = 2.48 s: the setting is used
        expected = 2 * cd + 3.0 + 5.0 - (short + short + 2.0)
        self.assertAlmostEqual(self.real_length(result.output_path), expected, delta=TOLERANCE_S)
        warnings = [m for m in self.sink.messages(Level.WARNING) if "shortened" in m]
        self.assertEqual(warnings, [f"2: Short - Artist: clip is only 3.00 s: crossfades next to it "
                                    f"shortened to {short:.2f} s (setting 2 s)"])


class CountdownFloorTest(PipelineTestCase):

    def test_countdown_under_three_frames_stops_the_run(self):
        real_measure = self.processor.measure
        self.processor.measure = lambda path, s, e: (ClipInfo(0.05, -3.0) if path == CD_MP3
                                                     else real_measure(path, s, e))
        with self.assertRaisesRegex(LarbError, "Countdown is 0.05 s long; it must be at least 0.10 s"):
            self.run_pipeline([row(2, "fx://sewer", "0:10-0:20")], FakeMedia({"fx://sewer": (SEWER, 67.0)}),
                              CD_MP3, Settings())


if __name__ == "__main__":
    unittest.main()
