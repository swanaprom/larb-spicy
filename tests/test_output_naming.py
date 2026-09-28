"""Output naming (slice 3): nothing unverified ever gets the final name.

The core renders to <name>.rendering.<ext>, checks the length, then renames it to
<name>.<ext> or <name>_FAILED.<ext>. Leftover .rendering files from a crashed run
are removed at the next run start, and nothing else in the folder is touched.
A fake processor stands in for FFmpeg, so each case is quick and exact.
"""

import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import CD_MP3, ROOT, SEWER, FakeMedia, FakeSongs, RecordingSink, row  # noqa: E402
from larb.core.errors import RenderError  # noqa: E402
from larb.core.models import ClipInfo, Level, ProcessingSettings, Settings  # noqa: E402
from larb.core.pipeline import Pipeline  # noqa: E402
from larb.core.ports import MediaProcessor  # noqa: E402

FILE_LENGTH_S = 60.0   # every input "file" is this long, as far as the fake knows


class FakeProcessor(MediaProcessor):
    """Writes a few bytes instead of rendering. Reports the planned length for the
    output, plus `length_error_s`, so a mismatch can be forced.

    Args:
        fail_after_writing: render writes something, then raises (FFmpeg crashed).
        fail_before_writing: render raises without writing anything.
    """

    def __init__(self, length_error_s=0.0, fail_after_writing=False, fail_before_writing=False):
        self.length_error_s = length_error_s
        self.fail_after_writing = fail_after_writing
        self.fail_before_writing = fail_before_writing
        self.rendered_to = None
        self._outputs = {}

    def measure(self, path, start_s, end_s):
        return ClipInfo(self._outputs.get(path, FILE_LENGTH_S), peak_db=-3.0)

    def render(self, plan, output_path):
        self.rendered_to = output_path
        if self.fail_before_writing:
            raise RenderError("ffmpeg.exe failed (exit code 1): no such filter")
        output_path.write_bytes(b"partial output")
        if self.fail_after_writing:
            raise RenderError("ffmpeg.exe failed (exit code 1): out of memory")
        self._outputs[output_path] = plan.expected_duration_s + self.length_error_s
        return output_path

    def describe(self):
        return "fake"


class OutputNamingTest(unittest.TestCase):

    def setUp(self):
        (ROOT / "workspace").mkdir(exist_ok=True)
        self.workspace = Path(tempfile.mkdtemp(prefix="test_", dir=ROOT / "workspace"))
        self.output_dir = self.workspace / "output"
        self.output_dir.mkdir()
        self.sink = RecordingSink()

    def tearDown(self):
        shutil.rmtree(self.workspace, ignore_errors=True)

    def run_with(self, processor):
        pipeline = Pipeline(FakeSongs([row(2, "fx://sewer", "0:10-0:20")]),
                            FakeMedia({"fx://sewer": (SEWER, 67.0)}), processor, self.sink, self.workspace)
        return pipeline.run("fake-sheet", str(CD_MP3), Settings(processing=ProcessingSettings(audio_only=True)),
                            now=datetime(2026, 9, 27, 14, 30, 12))

    def output_files(self):
        return sorted(p.name for p in self.output_dir.iterdir())

    def test_success_gets_only_the_final_name(self):
        processor = FakeProcessor()
        result = self.run_with(processor)
        self.assertEqual(processor.rendered_to.name, "2026-09-27_143012.rendering.mp3")
        self.assertEqual(result.output_path.name, "2026-09-27_143012.mp3")
        self.assertEqual(self.output_files(), ["2026-09-27_143012.mp3"])   # no temporary file left

    def test_length_mismatch_gives_only_a_failed_file(self):
        with self.assertRaisesRegex(RenderError, "(?s)should be .*kept as .*2026-09-27_143012_FAILED.mp3"):
            self.run_with(FakeProcessor(length_error_s=0.5))
        self.assertEqual(self.output_files(), ["2026-09-27_143012_FAILED.mp3"])

    def test_render_failing_after_writing_gives_only_a_failed_file(self):
        with self.assertRaisesRegex(RenderError, "(?s)out of memory.*kept as"):
            self.run_with(FakeProcessor(fail_after_writing=True))
        self.assertEqual(self.output_files(), ["2026-09-27_143012_FAILED.mp3"])

    def test_render_failing_before_writing_leaves_nothing(self):
        with self.assertRaisesRegex(RenderError, "no such filter"):
            self.run_with(FakeProcessor(fail_before_writing=True))
        self.assertEqual(self.output_files(), [])

    def test_failed_names_never_overwrite(self):
        (self.output_dir / "2026-09-27_143012_FAILED.mp3").write_bytes(b"earlier")
        with self.assertRaises(RenderError):
            self.run_with(FakeProcessor(length_error_s=-0.5))
        self.assertEqual(self.output_files(), ["2026-09-27_143012_FAILED.mp3", "2026-09-27_143012_FAILED_2.mp3"])
        self.assertEqual((self.output_dir / "2026-09-27_143012_FAILED.mp3").read_bytes(), b"earlier")

    def test_leftovers_removed_at_run_start_and_nothing_else(self):
        leftovers = ["2026-09-26_101010.rendering.mp3", "old.rendering.mp4"]
        others = ["2026-09-26_090000.mp3", "2026-09-26_080000_FAILED.mp4", "notes.rendering.txt",
                  "my.rendering.mp3.bak", "song.mp3"]
        for name in leftovers + others:
            (self.output_dir / name).write_bytes(b"x")
        (self.output_dir / "folder.rendering.mp4").mkdir()           # a folder, not a file
        processor = FakeProcessor(fail_before_writing=True)          # the cleanup happens even if the run fails
        with self.assertRaises(RenderError):
            self.run_with(processor)
        self.assertEqual(self.output_files(), sorted(others + ["folder.rendering.mp4"]))
        removed = [m for m in self.sink.messages(Level.INFO) if "leftover" in m]
        self.assertEqual(len(removed), 2)

    @unittest.skipUnless(sys.platform == "win32", "only Windows refuses to delete an open file")
    def test_locked_leftover_is_skipped_with_a_warning(self):
        locked = self.output_dir / "busy.rendering.mp4"
        with open(locked, "wb"):                                      # held open, like a running FFmpeg
            result = self.run_with(FakeProcessor())
            self.assertTrue(locked.exists())
        self.assertTrue(result.output_path.is_file())
        self.assertIn("Can't remove leftover busy.rendering.mp4", " | ".join(self.sink.messages(Level.WARNING)))


if __name__ == "__main__":
    unittest.main()
