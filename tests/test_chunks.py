"""Video in chunks (slice 3): chunks are cut inside a countdown on a frame boundary,
rendered separately, joined without re-encoding, and the one-pass audio is added.
The result must match the plan as a one-pass render would."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import CD_MP4, THAI_MP4, FakeMedia, PipelineTestCase, row  # noqa: E402
from larb.adapters.ffmpeg import processor  # noqa: E402
from larb.adapters.ffmpeg.helper import run_tool  # noqa: E402
from larb.adapters.ffmpeg.processor import FPS, frames_for, split_into_chunks  # noqa: E402
from larb.core.models import (DownloadSettings, Level, ProcessingSettings, RenderPlan,  # noqa: E402
                              Segment, Settings)
from larb.core.pipeline import plan_crossfades  # noqa: E402

TOLERANCE_S = 0.1
FRAME = 1 / FPS


def plan_of(durations, crossfade=1.0):
    segs = tuple(Segment(Path(f"clip{i}.mp4"), 10.0, 10.0 + d, False, 0.0) for i, d in enumerate(durations))
    joins, fade = plan_crossfades(list(durations), crossfade)
    return RenderPlan(segs, joins, False, 720, fade)


class SplitTest(unittest.TestCase):

    def test_chunks_add_up_to_the_plan_and_are_whole_frames(self):
        plan = plan_of([5.341, 37.2, 5.341, 12.05, 5.341, 40.0, 5.341, 9.9, 5.341, 30.0, 5.341, 7.0, 5.341, 3.0])
        chunks = split_into_chunks(plan, 4)
        self.assertEqual(len(chunks), 4)                 # cuts inside segments 4, 8 and 12
        self.assertAlmostEqual(sum(c.expected_duration_s for c in chunks), plan.expected_duration_s, places=6)
        for chunk in chunks[:-1]:
            frames = chunk.expected_duration_s * FPS
            self.assertAlmostEqual(frames, round(frames), places=6)
            self.assertEqual(chunk.fade_out_s, 0.0)
        self.assertEqual(chunks[-1].fade_out_s, plan.fade_out_s)
        self.assertEqual(frames_for(plan.expected_duration_s),
                         sum(frames_for(c.expected_duration_s) for c in chunks))

    def test_cut_is_inside_the_countdown_between_its_crossfades(self):
        plan = plan_of([5.341, 37.2, 5.341, 12.05, 5.341, 40.0], crossfade=2.0)
        first, second, _ = split_into_chunks(plan, 2)     # cuts inside segments 2 and 4
        countdown_used = first.segments[-1].duration_s     # the countdown's part in chunk 1
        self.assertGreaterEqual(countdown_used, 2.0)      # after its incoming crossfade ...
        self.assertGreaterEqual(second.segments[0].duration_s, 2.0)    # ... and before its outgoing one
        self.assertAlmostEqual(countdown_used + second.segments[0].duration_s, 5.341, places=6)
        self.assertEqual(first.segments[-1].path, second.segments[0].path)

    def test_cut_fits_a_countdown_with_only_one_frame_to_itself(self):
        # A countdown barely longer than two crossfades: the crossfade rule leaves one frame.
        plan = plan_of([10.0, 2.0 + FRAME, 10.0, 2.0 + FRAME, 10.0], crossfade=1.0)
        chunks = split_into_chunks(plan, 1)
        self.assertEqual(len(chunks), 4)
        for chunk in chunks:
            for seg in chunk.segments:
                self.assertGreater(seg.duration_s, 0)

    def test_short_list_is_one_chunk(self):
        plan = plan_of([5.341, 37.2, 5.341, 12.05])
        self.assertEqual(split_into_chunks(plan, 6), [plan])


class ChunkedRenderTest(PipelineTestCase):

    def stream_lengths(self, path):
        result = run_tool(self.tools.ffprobe, ["-v", "error", "-show_entries", "stream=codec_type,duration",
                                               "-of", "csv=p=0", str(path)])
        return {kind: float(length) for kind, length in
                (line.split(",") for line in result.stdout.split())}

    def test_three_chunks_match_the_plan(self):
        media = FakeMedia({"fx://thai": (THAI_MP4, 8.0)})
        rows = [row(2, "fx://thai", "0:01-0:05"), row(3, "fx://thai", "0:02-0:06", mirrored="1"),
                row(4, "fx://thai", "0:03-0:07")]
        settings = Settings(processing=ProcessingSettings(audio_only=False, mirror=True, crossfade_duration_seconds=1.0),
                            download=DownloadSettings(max_height=360))
        with mock.patch.object(processor, "CHUNK_SEGMENTS", 2):      # 6 segments -> 3 chunks
            result = self.run_pipeline(rows, media, CD_MP4, settings)

        cd, thai = self.real_length(CD_MP4), self.real_length(THAI_MP4)
        expected = 3 * cd + (6 - 0) + (7 - 1) + (min(thai, 8) - 2) - 5 * 1.0
        self.assertAlmostEqual(self.real_length(result.output_path), expected, delta=TOLERANCE_S)
        lengths = self.stream_lengths(result.output_path)
        self.assertAlmostEqual(lengths["video"], expected, delta=FRAME)
        self.assertAlmostEqual(lengths["audio"], lengths["video"], delta=FRAME)
        parts = [e.progress for e in self.sink.events if e.stage == "render" and e.progress]
        self.assertEqual(parts, [(1, 3), (2, 3), (3, 3)])
        self.assertEqual(list((self.workspace / "tmp").iterdir()), [])   # chunks and graphs cleaned up
        self.assertFalse([m for m in self.sink.messages(Level.WARNING) if "shortened" in m])


if __name__ == "__main__":
    unittest.main()
