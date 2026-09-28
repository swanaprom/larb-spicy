"""Audio length over many segments (slice 3).

YouTube's audio downloads are Opus (.webm), and an Opus file's container reports a
few ms more than the audio that actually decodes (TECH §16). A countdown is used
whole, so each one came out that much short of the plan, and a long list failed
the length check. The renderer now pads/cuts every audio segment to its planned
length. The fixture is a generated tone with the same property:

    ffmpeg -f lavfi -i sine=frequency=440:duration=3:sample_rate=48000 -ac 2
           -c:a libopus -b:a 48k -map_metadata -1 tests/fixtures/countdown/tone_3s.webm

(container 3.008 s, decodes to 3.000 s).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import CD_OPUS, SEWER, FakeMedia, PipelineTestCase, row  # noqa: E402
from larb.core.models import ProcessingSettings, Settings  # noqa: E402

SONGS = 20                  # 20 songs + 20 countdowns = 40 segments
TIGHT_TOLERANCE_S = 0.02    # stricter than the pipeline's own check (0.1 s)


class AudioLengthTest(PipelineTestCase):

    def test_the_fixture_still_has_the_opus_gap(self):
        """Guard: if the fixture decoded to its container length, this test file would prove nothing."""
        self.assertGreater(self.real_length(CD_OPUS) - 3.0, 0.005)

    def test_many_opus_countdowns_keep_the_planned_length(self):
        media = FakeMedia({"fx://sewer": (SEWER, 67.0)})
        # 2 s ranges at different places; with padding each clip is 4 s.
        rows = [row(n + 2, "fx://sewer", f"0:{10 + 2 * n:02d}-0:{12 + 2 * n:02d}") for n in range(SONGS)]
        settings = Settings(processing=ProcessingSettings(audio_only=True))
        result = self.run_pipeline(rows, media, CD_OPUS, settings)   # raised RenderError before the fix

        cd = self.real_length(CD_OPUS)
        expected = SONGS * cd + SONGS * 4.0 - (2 * SONGS - 1) * 1.0
        self.assertAlmostEqual(self.real_length(result.output_path), expected, delta=TIGHT_TOLERANCE_S)


if __name__ == "__main__":
    unittest.main()
