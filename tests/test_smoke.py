"""Smoke test: the whole pipeline, fully offline, from tests/fixtures/ only.

Fake song list and fake media source (no sheet fetch, no YouTube); the REAL
FFmpeg processor. Checks the output's length, not just that it exists: FFmpeg
can succeed and still write a wrong file (TECH §10).

Run from the repository root:
    .venv\\Scripts\\python.exe -m unittest -v
"""

import math
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import (CD_MP3, CD_MP4, SEWER, THAI_MP4, XG, FakeMedia,  # noqa: E402
                   PipelineTestCase, row)
from larb.adapters.ffmpeg.helper import run_tool  # noqa: E402
from larb.core.models import DownloadSettings, Level, ProcessingSettings, Settings  # noqa: E402

TOLERANCE_S = 0.1
# End fade-out checks: the last moment must be (near) silent and (near) black,
# while a moment before the fade still has sound, so the check can't pass by accident.
END_WINDOW_S = 0.02     # the last this-many seconds are checked
SILENT_DB = -30.0       # peak in the end window must be below this
BLACK_LUMA = 30         # average brightness of the last frame (0-255; video black is 16). The last
                        # frame starts 1/30 s before the end, so a little picture is left: ~20 measured,
                        # vs ~138 without the fade.


class SmokeTest(PipelineTestCase):

    def assert_fades_to_silence(self, output, length, loud_before=True):
        """loud_before: also check there's sound just before the fade (only when the
        last song is loud right up to its end)."""
        end_peak = self.processor.measure(output, length - END_WINDOW_S, None).peak_db
        self.assertLess(end_peak, SILENT_DB, "the output should end (near) silent")
        if loud_before:
            before_fade = self.processor.measure(output, length - 2.5, length - 1.5).peak_db
            self.assertGreater(before_fade, SILENT_DB, "the output should have sound before the fade")

    def last_frame_luma(self, output):
        """Average brightness of the last frames, read with FFmpeg's signalstats filter."""
        result = run_tool(self.tools.ffmpeg, [
            "-hide_banner", "-sseof", "-0.2", "-i", str(output), "-an",
            "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"])
        values = re.findall(r"lavfi\.signalstats\.YAVG=([\d.]+)", result.stderr)
        self.assertTrue(values, "signalstats reported no frames")
        return float(values[-1])

    def test_audio_only(self):
        sewer_len = self.real_length(SEWER)                  # 66.51 s
        media = FakeMedia({
            "fx://xg": (XG, 189.0),
            "fx://sewer": (SEWER, math.ceil(sewer_len)),     # rounded up, like YouTube
            "fx://sewer-lying": (SEWER, 70.0),               # claims 70 s; real file is 66.5 s
        }, fail_first={"fx://xg"})
        rows = [
            row(2, "fx://xg", "0:30 - 0:40"),
            row(3, "fx://sewer", "0.1 0-0:20", artist=""),   # stray space; missing artist -> warning
            row(4, "fx://xg", "1.5-2:00"),                   # bad time -> row error
            row(5, "fx://sewer", "0:50-1:07"),               # 0.49 s past real end -> trim + warning
            row(6, "fx://sewer-lying", "1:00-1:09"),         # 2.5 s past real end -> row error
            row(7, "fx://missing", "0:10-0:20"),             # unavailable -> row error
        ]
        settings = Settings(processing=ProcessingSettings(audio_only=True, mirror=True, crossfade_duration_seconds=1.0),
                            download=DownloadSettings(max_parallel_downloads=2, max_retries=2))
        result = self.run_pipeline(rows, media, CD_MP3, settings)

        cd = self.real_length(CD_MP3)
        expected = 3 * cd + (41 - 29) + (21 - 9) + (sewer_len - 49) - 5 * 1.0
        self.assertEqual(result.output_path.name, "2026-09-27_143012.mp3")
        actual = self.real_length(result.output_path)
        self.assertAlmostEqual(actual, expected, delta=TOLERANCE_S)   # the fade-out adds no length
        # The last song runs to the (already quiet) end of its file: only the end is checked here.
        self.assert_fades_to_silence(result.output_path, actual, loud_before=False)
        self.assertEqual(result.songs_rendered, 3)
        self.assertEqual(media.downloads, 3)   # xg + sewer + sewer-lying; sewer used twice = one download
        errors = " | ".join(self.sink.messages(Level.ERROR))
        warnings = " | ".join(self.sink.messages(Level.WARNING))
        for expected_error in ("4: skipped", "6: skipped: end", "7: skipped: video unavailable"):
            self.assertIn(expected_error, errors)
        for expected_warning in ("3: artist is empty", "5: end 67 s", "retry 1/2"):
            self.assertIn(expected_warning, warnings)

        # Same settings again: everything comes from the cache.
        media.downloads = 0
        again = self.run_pipeline(rows, media, CD_MP3, settings)
        self.assertEqual(media.downloads, 0)
        self.assertEqual(again.output_path.name, "2026-09-27_143012_2.mp3")   # never overwrites

    def test_audio_fade_out(self):
        """The last song is loud up to its end, so the silence at the end is the fade-out's doing."""
        media = FakeMedia({"fx://xg": (XG, 189.0)})
        settings = Settings(processing=ProcessingSettings(audio_only=True, crossfade_duration_seconds=1.0))
        result = self.run_pipeline([row(2, "fx://xg", "0:30-0:40")], media, CD_MP3, settings)
        expected = self.real_length(CD_MP3) + (41 - 29) - 1.0
        actual = self.real_length(result.output_path)
        self.assertAlmostEqual(actual, expected, delta=TOLERANCE_S)   # the fade-out adds no length
        self.assert_fades_to_silence(result.output_path, actual)

    def test_video_mirror(self):
        media = FakeMedia({"fx://thai": (THAI_MP4, 8.0)})
        rows = [
            row(2, "fx://thai", "0:01-0:05"),                 # gets mirrored
            row(3, "fx://thai", "0:02-0:06", mirrored="1"),   # already mirrored: left as is
            row(4, "fx://thai", "0:03-0:07", mirrored="   "), # only spaces = not mirrored yet
        ]
        settings = Settings(processing=ProcessingSettings(audio_only=False, mirror=True, crossfade_duration_seconds=1.0),
                            download=DownloadSettings(max_height=360))
        result = self.run_pipeline(rows, media, CD_MP4, settings)

        cd, thai = self.real_length(CD_MP4), self.real_length(THAI_MP4)
        expected = 3 * cd + (6 - 0) + (7 - 1) + (min(thai, 8) - 2) - 5 * 1.0
        self.assertEqual(result.output_path.suffix, ".mp4")
        actual = self.real_length(result.output_path)
        self.assertAlmostEqual(actual, expected, delta=TOLERANCE_S)   # the fade-out adds no length
        self.assert_fades_to_silence(result.output_path, actual)
        self.assertLess(self.last_frame_luma(result.output_path), BLACK_LUMA, "the video should end black")
        self.assertEqual(media.downloads, 1)                  # same video three times
        mirror_log = [e.message for e in self.sink.events if e.stage == "measure" and e.level is Level.DEBUG
                      and "mirror" in e.message]
        self.assertEqual([m.endswith("mirror True") for m in mirror_log], [True, False, True])


if __name__ == "__main__":
    unittest.main()
