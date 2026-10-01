"""Cache-aware checking (slice 6, SPEC §9 stage 4): a row whose file for this run's mode
is cached is not looked up; its length is measured from the file. The countdown too."""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import CD_MP3, SEWER, THAI_MP4, XG, FakeMedia, PipelineTestCase, row  # noqa: E402
from larb.core.models import DownloadSettings, Level, ProcessingSettings, Settings  # noqa: E402

AUDIO = Settings(processing=ProcessingSettings(audio_only=True))
CD_URL = "https://cd"


class CacheAwareTest(PipelineTestCase):

    def cache(self, source: Path, name: str) -> None:
        """Put a file in the run's cache under a cache name, e.g. "xg_audio.mp3"."""
        folder = self.workspace / "cache"
        folder.mkdir(exist_ok=True)
        shutil.copyfile(source, folder / name)

    def media(self, **kwargs):
        # The reported lengths lie on purpose: a cached row must not use them.
        return FakeMedia({CD_URL: (CD_MP3, 999.0), "fx://xg": (XG, 999.0), "fx://sewer": (SEWER, 999.0)},
                         **kwargs)

    def test_cached_rows_and_countdown_make_no_lookups(self):
        self.cache(CD_MP3, "cd_audio.mp3")
        self.cache(XG, "xg_audio.mp3")
        self.cache(SEWER, "sewer_audio.mp3")
        media = self.media()
        result = self.run_pipeline([row(2, "fx://xg", "0:10-0:20"), row(3, "fx://sewer", "0:30-0:40")],
                                   media, CD_URL, AUDIO)
        self.assertEqual((media.lookups, media.downloads), (0, 0))
        self.assertEqual(result.songs_rendered, 2)
        info = self.sink.messages(Level.INFO)
        self.assertEqual(len([m for m in info if "cached, not looked up" in m]), 3)   # 2 rows + countdown
        self.assertIn("None: 2 of 2 row(s) usable: 2 checked from the cache, 0 looked up", info)

    def test_second_identical_run_makes_no_lookups(self):
        rows = [row(2, "fx://xg", "0:10-0:20"), row(3, "fx://sewer", "0:30-0:40")]
        first = self.media()
        self.run_pipeline(rows, first, CD_URL, AUDIO)
        self.assertEqual(first.lookups, 3)
        second = self.media()
        self.run_pipeline(rows, second, CD_URL, AUDIO)
        self.assertEqual((second.lookups, second.downloads), (0, 0))

    def test_cached_only_in_the_other_mode_is_looked_up(self):
        self.cache(CD_MP3, "cd_audio.mp3")
        self.cache(THAI_MP4, "xg_v720.mp4")     # a video-mode file: no use for an audio run
        self.cache(SEWER, "sewer_audio.mp3")
        media = self.media()
        self.run_pipeline([row(2, "fx://xg", "0:10-0:20"), row(3, "fx://sewer", "0:30-0:40")],
                          media, CD_URL, AUDIO)
        self.assertEqual(media.lookup_urls, ["fx://xg"])
        self.assertEqual(media.downloads, 1)

    def test_length_rules_apply_to_the_measured_length(self):
        """sewer is 66.51 s: an end 0.49 s past it is trimmed with a warning (the strict early
        check would have rejected it), 2.49 s past it is a row error."""
        self.cache(CD_MP3, "cd_audio.mp3")
        self.cache(SEWER, "sewer_audio.mp3")
        media = self.media()
        result = self.run_pipeline([row(2, "fx://sewer", "1:00-1:07"), row(3, "fx://sewer", "1:00-1:09")],
                                   media, CD_URL, AUDIO)
        self.assertEqual(media.lookups, 0)
        self.assertEqual(result.songs_rendered, 1)
        self.assertTrue([m for m in self.sink.messages(Level.WARNING) if m.startswith("2:") and "trimmed" in m])
        self.assertTrue([m for m in self.sink.messages(Level.ERROR) if m.startswith("3:") and "past" in m])

    def test_url_without_a_known_id_is_looked_up(self):
        self.cache(XG, "xg_audio.mp3")
        media = self.media(knows_ids=False)
        self.run_pipeline([row(2, "fx://xg", "0:10-0:20")], media, CD_URL, AUDIO)
        self.assertEqual(sorted(media.lookup_urls), sorted([CD_URL, "fx://xg"]))

    def test_video_mode_uses_its_own_cache_name(self):
        self.cache(CD_MP3, "cd_v360.mp3")
        self.cache(THAI_MP4, "thai_v360.mp4")
        media = FakeMedia({CD_URL: (CD_MP3, 999.0), "fx://thai": (THAI_MP4, 999.0)})
        settings = Settings(processing=ProcessingSettings(audio_only=False),
                            download=DownloadSettings(max_height=360))
        self.run_pipeline([row(2, "fx://thai", "0:01-0:05")], media, CD_URL, settings)
        self.assertEqual(media.lookups, 0)


if __name__ == "__main__":
    unittest.main()
