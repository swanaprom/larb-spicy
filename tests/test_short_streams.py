"""A clip whose video or audio ends early (slice 3).

The renderer pads a short stream (the last frame repeated, or silence), so the
output keeps its planned length. More than 0.5 s short may be a real problem (a
frozen picture), so it's warned about: a row warning for a song, one warning per
run for the countdown. "Short" is judged against the whole clip, padding included.

Fixtures (tests/fixtures/short/), generated with FFmpeg:

    ffmpeg -f lavfi -i testsrc=size=320x180:rate=30:duration=4
           -f lavfi -i sine=frequency=330:duration=6:sample_rate=48000
           -c:v libx264 -pix_fmt yuv420p -c:a aac -b:a 64k -map_metadata -1 video_4s_audio_6s.mp4
    (and video_6s_audio_4s.mp4: testsrc duration=6, sine frequency=550:duration=4)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import CD_MP4, FIX, THAI_MP4, FakeMedia, PipelineTestCase, row  # noqa: E402
from larb.core.models import DownloadSettings, Level, ProcessingSettings, Settings  # noqa: E402

SHORT_VIDEO = FIX / "short" / "video_4s_audio_6s.mp4"
SHORT_AUDIO = FIX / "short" / "video_6s_audio_4s.mp4"
TOLERANCE_S = 0.1
VIDEO = Settings(processing=ProcessingSettings(audio_only=False),
                 download=DownloadSettings(max_height=360))


class MeasureStreamsTest(PipelineTestCase):

    def test_measure_reports_each_stream(self):
        info = self.processor.measure(SHORT_VIDEO, 0.0, None)
        self.assertAlmostEqual(info.duration_s, 6.0, delta=0.1)
        self.assertAlmostEqual(info.video_s, 4.0, delta=0.05)
        self.assertAlmostEqual(info.audio_s, 6.0, delta=0.05)

    def test_measure_counts_only_the_range(self):
        info = self.processor.measure(SHORT_AUDIO, 1.0, 5.5)     # audio ends at 4 s
        self.assertAlmostEqual(info.video_s, 4.5, delta=0.05)
        self.assertAlmostEqual(info.audio_s, 3.0, delta=0.05)

    def test_audio_only_file_has_no_video(self):
        info = self.processor.measure(FIX / "sewer. [Instrumental].mp3", 0.0, 10.0)
        self.assertIsNone(info.video_s)
        self.assertAlmostEqual(info.audio_s, 10.0, delta=0.05)


class ShortStreamWarningTest(PipelineTestCase):

    def short_warnings(self):
        return [m for m in self.sink.messages(Level.WARNING) if "shorter than the clip" in m]

    def test_normal_clips_give_no_warning(self):
        media = FakeMedia({"fx://thai": (THAI_MP4, 8.0)})
        self.run_pipeline([row(2, "fx://thai", "0:01-0:05")], media, CD_MP4, VIDEO)
        self.assertEqual(self.short_warnings(), [])

    def test_short_countdown_video_warns_once_per_run(self):
        media = FakeMedia({"fx://thai": (THAI_MP4, 8.0)})
        rows = [row(2, "fx://thai", "0:01-0:05"), row(3, "fx://thai", "0:02-0:06")]
        result = self.run_pipeline(rows, media, SHORT_VIDEO, VIDEO)
        warnings = self.short_warnings()
        self.assertEqual(len(warnings), 1, warnings)
        self.assertRegex(warnings[0], r"^None: countdown: video is 2\.\d\d s shorter than the clip "
                                      r"\(6\.\d\d s\); the last frame is repeated")
        cd, thai = self.real_length(SHORT_VIDEO), self.real_length(THAI_MP4)
        expected = 2 * cd + (6 - 0) + (7 - 1) - 3 * 1.0            # padding keeps the planned length
        self.assertAlmostEqual(self.real_length(result.output_path), expected, delta=TOLERANCE_S)

    def test_short_song_audio_gives_a_row_warning(self):
        media = FakeMedia({"fx://short": (SHORT_AUDIO, 6.0), "fx://thai": (THAI_MP4, 8.0)})
        rows = [row(2, "fx://short", "0:01-0:04", title="Gap"),     # clip 0-5 s, audio only to 4 s
                row(3, "fx://thai", "0:01-0:05")]
        result = self.run_pipeline(rows, media, CD_MP4, VIDEO)
        warnings = self.short_warnings()
        self.assertEqual(len(warnings), 1, warnings)
        # ~1 s: AAC's encoder padding makes the 4 s tone decode to ~4.01 s
        self.assertRegex(warnings[0], r"^2: Gap - Artist: audio is (0\.9|1\.0)\d s shorter than the clip "
                                      r"\(5\.00 s\); silence is added")
        cd = self.real_length(CD_MP4)
        expected = 2 * cd + (5 - 0) + (6 - 0) - 3 * 1.0
        self.assertAlmostEqual(self.real_length(result.output_path), expected, delta=TOLERANCE_S)

    def test_stream_ending_with_the_clip_gives_no_warning(self):
        # clip 0-4 s of the short-audio file, whose audio ends at 4 s: nothing is missing
        media = FakeMedia({"fx://short": (SHORT_AUDIO, 6.0)})
        self.run_pipeline([row(2, "fx://short", "0:01-0:03")], media, CD_MP4, VIDEO)
        self.assertEqual(self.short_warnings(), [])


if __name__ == "__main__":
    unittest.main()
