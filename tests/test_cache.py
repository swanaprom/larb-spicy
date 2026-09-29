"""Clearing the download cache, and the question asked after a run."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import ROOT, RecordingSink  # noqa: E402  (also puts src/ on the path)
from larb.cli import offer_cache_clear  # noqa: E402
from larb.core.cache import cache_summary, clear_cache, remove_leftovers  # noqa: E402

CACHE_FILES = ["oKBwWQI-IoI_audio.webm", "oKBwWQI-IoI_v720.mp4", "qW9N8XjUkIE_v1080.mp4",
               "abc_v720.f136.mp4.part", "abc_audio.webm.part", "abc_v720.temp.mp4", "abc_audio.webm.ytdl"]
# An operator may point the cache at a folder that holds other files too.
OTHER_FILES = ["my holiday.mp4", "notes.txt", "audio.mp3", "oKBwWQI-IoI.mp4", "x_video.mp4"]


class CacheTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "workspace").mkdir(exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix="test_cache_", dir=ROOT / "workspace"))
        for name in CACHE_FILES + OTHER_FILES:
            (self.dir / name).write_bytes(b"x")
        (self.dir / "sub_audio.d").mkdir()                       # folders are never touched
        self.sink = RecordingSink()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def names(self):
        return sorted(p.name for p in self.dir.iterdir())

    def test_clear_deletes_only_cache_files(self):
        self.assertEqual(clear_cache(self.dir), len(CACHE_FILES))
        self.assertEqual(self.names(), sorted(OTHER_FILES + ["sub_audio.d"]))

    def test_summary_counts_what_clear_would_delete(self):
        (self.dir / "oKBwWQI-IoI_audio.webm").write_bytes(b"x" * 1000)
        self.assertEqual(cache_summary(self.dir), (len(CACHE_FILES), 1000 + len(CACHE_FILES) - 1))
        self.assertEqual(cache_summary(self.dir / "missing"), (0, 0))
        self.assertEqual(clear_cache(self.dir), len(CACHE_FILES))
        self.assertEqual(cache_summary(self.dir), (0, 0))

    def test_leftovers_of_one_download(self):
        """After a stopped download: only that stem's pieces go, finished downloads stay."""
        removed = remove_leftovers(self.dir, "abc_v720")
        self.assertEqual(sorted(p.name for p in removed), ["abc_v720.f136.mp4.part", "abc_v720.temp.mp4"])
        self.assertIn("abc_audio.webm.part", self.names())            # another kind: not this download
        self.assertIn("oKBwWQI-IoI_v720.mp4", self.names())
        self.assertEqual(remove_leftovers(self.dir, "oKBwWQI-IoI"), [])  # "<id>." never matches a cache name

    def test_not_interactive_never_asks(self):
        def ask(_):
            raise AssertionError("must not ask when not interactive")
        self.assertFalse(offer_cache_clear(self.dir, self.sink, interactive=False, ask=ask))
        self.assertEqual(len(self.names()), len(CACHE_FILES + OTHER_FILES) + 1)

    def test_enter_means_no(self):
        for answer in ("", "n", "no", "whatever"):
            self.assertFalse(offer_cache_clear(self.dir, self.sink, interactive=True, ask=lambda _: answer))
        self.assertEqual(len(self.names()), len(CACHE_FILES + OTHER_FILES) + 1)

    def test_closed_input_means_no(self):
        def ask(_):
            raise EOFError
        self.assertFalse(offer_cache_clear(self.dir, self.sink, interactive=True, ask=ask))

    def test_yes_clears(self):
        prompts = []
        self.assertTrue(offer_cache_clear(self.dir, self.sink, interactive=True,
                                          ask=lambda p: prompts.append(p) or " Y "))
        self.assertEqual(prompts, ["Clear the download cache? [y/N] "])
        self.assertEqual(self.names(), sorted(OTHER_FILES + ["sub_audio.d"]))


if __name__ == "__main__":
    unittest.main()
