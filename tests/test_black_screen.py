"""A clip without a picture in video mode: a black screen with its sound (SPEC §9 stage 3).

Fixture `countdown/cover_art.mp3` is `!countdown.mp3` with a 64x64 red cover image
attached, made with:
    ffmpeg -f lavfi -i color=c=red:s=64x64 -frames:v 1 red.jpg
    ffmpeg -i "!countdown.mp3" -i red.jpg -map 0:a -map 1:v -c copy
           -disposition:v:0 attached_pic -id3v2_version 3 cover_art.mp3
A cover image is not a picture: the countdown must be black, not red.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import CD_MP3, CD_MP4, FIX, THAI_MP4, XG, FakeMedia, PipelineTestCase, row  # noqa: E402
from larb.adapters.ffmpeg.helper import run_tool  # noqa: E402
from larb.core.models import DownloadSettings, Level, ProcessingSettings, Settings  # noqa: E402

CD_COVER = FIX / "countdown" / "cover_art.mp3"
VIDEO = Settings(processing=ProcessingSettings(audio_only=False, crossfade_duration_seconds=1.0),
                 download=DownloadSettings(max_height=360))
SONGS = [row(2, "fx://thai", "0:01-0:05"), row(3, "fx://thai", "0:02-0:06")]   # 6 s clips with padding
BLACK_Y = 20       # average luma of a black frame is 16 (limited range)


class BlackScreenTest(PipelineTestCase):

    def frame_yuv(self, path, at_s):
        """Average Y, U, V of the frame at at_s seconds."""
        result = run_tool(self.tools.ffmpeg, ["-hide_banner", "-ss", f"{at_s:.3f}", "-i", str(path),
                                              "-frames:v", "1", "-vf", "signalstats,metadata=print",
                                              "-f", "null", "-"])
        return tuple(float(re.search(rf"signalstats\.{c}AVG=([\d.]+)", result.stderr).group(1))
                     for c in "YUV")

    def picture_warnings(self):
        return [m for m in self.sink.messages(Level.WARNING) if "no picture" in m]

    def check_countdowns_black(self, countdown):
        result = self.run_pipeline(SONGS, FakeMedia({"fx://thai": (THAI_MP4, 8.0)}), countdown, VIDEO)
        cd = self.real_length(countdown)
        # Layout, crossfades 1 s: countdown [0, cd], song [cd-1, cd+5], countdown [cd+4, 2cd+4], song.
        expected = 2 * cd + 2 * 6 - 3 * 1.0
        self.assertAlmostEqual(self.real_length(result.output_path), expected, delta=0.1)
        for middle in ((cd - 1) / 2, 1.5 * cd + 4):           # the parts that play on their own
            y, _u, v = self.frame_yuv(result.output_path, middle)
            self.assertLess(y, BLACK_Y, msg=f"countdown at {middle:.2f} s is not black")
            self.assertLess(v, 140, msg="the cover image (red) is shown")
        y, _u, _v = self.frame_yuv(result.output_path, cd + 2)  # a song: a real picture
        self.assertGreater(y, BLACK_Y + 10)
        # With its sound: the countdown's audio is in the output.
        self.assertGreater(self.processor.measure(result.output_path, 0.5, cd - 1).peak_db, -20)
        return result

    def test_mp3_countdown_in_video_mode_is_black_with_one_warning(self):
        self.check_countdowns_black(CD_MP3)
        self.assertEqual(len(self.picture_warnings()), 1, msg=self.picture_warnings())   # 2 countdowns, 1 warning
        self.assertIn("None:", self.picture_warnings()[0])   # a run warning, not a row warning

    def test_cover_art_is_not_a_picture(self):
        self.check_countdowns_black(CD_COVER)
        self.assertEqual(len(self.picture_warnings()), 1)

    def test_song_without_picture_is_black_with_a_row_warning(self):
        media = FakeMedia({"fx://xg": (XG, 189.0)})
        result = self.run_pipeline([row(2, "fx://xg", "0:10-0:20")], media, CD_MP4, VIDEO)
        cd = self.real_length(CD_MP4)
        expected = cd + 12 - 1.0                                 # song 9-21 s with padding
        self.assertAlmostEqual(self.real_length(result.output_path), expected, delta=0.1)
        y, _u, _v = self.frame_yuv(result.output_path, cd + 5)
        self.assertLess(y, BLACK_Y)
        self.assertEqual([m.split(":")[0] for m in self.picture_warnings()], ["2"])

    def test_audio_mode_never_warns(self):
        settings = Settings(processing=ProcessingSettings(audio_only=True))
        self.run_pipeline(SONGS[:1], FakeMedia({"fx://thai": (THAI_MP4, 8.0)}), CD_MP3, settings)
        self.assertEqual(self.picture_warnings(), [])


if __name__ == "__main__":
    unittest.main()
