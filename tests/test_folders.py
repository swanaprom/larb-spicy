"""Folder settings (slice 5): relative paths start in the project folder, the default is
saved as "", and a folder that can't be created stops the run before anything downloads."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import CD_MP3, XG, FakeMedia, FakeSongs, PipelineTestCase, row  # noqa: E402
from larb.core.errors import LarbError  # noqa: E402
from larb.core.models import OutputSettings, ProcessingSettings, Settings  # noqa: E402
from larb.core.pipeline import Pipeline  # noqa: E402
from larb.core.settings import ensure_folder, folder_setting, resolve_folder  # noqa: E402

PROJECT = Path("D:/project") if sys.platform == "win32" else Path("/project")
WORKSPACE = PROJECT / "workspace"


class ResolveFolderTest(unittest.TestCase):
    def test_empty_is_the_default_in_workspace(self):
        self.assertEqual(resolve_folder("", "output", PROJECT, WORKSPACE), WORKSPACE / "output")
        self.assertEqual(resolve_folder("  ", "cache", PROJECT, WORKSPACE), WORKSPACE / "cache")

    def test_relative_starts_in_the_project_folder(self):
        # SPEC §14: "workspace/output" used to become workspace/workspace/output.
        self.assertEqual(resolve_folder("workspace/output", "output", PROJECT, WORKSPACE),
                         WORKSPACE / "output")
        self.assertEqual(resolve_folder("renders", "output", PROJECT, WORKSPACE), PROJECT / "renders")

    def test_absolute_is_kept(self):
        elsewhere = PROJECT.parent / "งานเต้น" / "out"
        self.assertEqual(resolve_folder(str(elsewhere), "output", PROJECT, WORKSPACE), elsewhere)


class FolderSettingTest(unittest.TestCase):
    """What the GUI saves for a folder it shows as a full path."""

    def test_default_is_saved_empty(self):
        self.assertEqual(folder_setting(str(WORKSPACE / "output"), "output", PROJECT, WORKSPACE), "")
        self.assertEqual(folder_setting("workspace/output", "output", PROJECT, WORKSPACE), "")
        self.assertEqual(folder_setting("", "output", PROJECT, WORKSPACE), "")

    def test_other_folder_is_saved_in_full(self):
        elsewhere = PROJECT.parent / "out"
        self.assertEqual(folder_setting(str(elsewhere), "output", PROJECT, WORKSPACE), str(elsewhere))
        self.assertEqual(folder_setting("renders", "output", PROJECT, WORKSPACE), str(PROJECT / "renders"))
        # The cache's default is a different folder.
        self.assertEqual(folder_setting(str(WORKSPACE / "output"), "cache", PROJECT, WORKSPACE),
                         str(WORKSPACE / "output"))


class FolderPipelineTest(PipelineTestCase):
    def pipeline(self, media, project_dir):
        return Pipeline(FakeSongs([row(2, "fx://xg", "0:10-0:20")]), media, self.processor, self.sink,
                        self.workspace, project_dir=project_dir)

    def test_relative_output_lands_in_the_project_folder(self):
        project = self.workspace / "project"
        settings = Settings(output=OutputSettings(directory="renders/today"),
                            processing=ProcessingSettings(audio_only=True))
        result = self.pipeline(FakeMedia({"fx://xg": (XG, 189.0)}), project).run(
            "fake-sheet", str(CD_MP3), settings)
        self.assertEqual(result.output_path.parent, project / "renders" / "today")
        self.assertTrue(result.output_path.is_file())

    def test_missing_output_folder_is_created(self):
        wanted = self.workspace / "new" / "deeper"
        settings = Settings(output=OutputSettings(directory=str(wanted)),
                            processing=ProcessingSettings(audio_only=True))
        result = self.pipeline(FakeMedia({"fx://xg": (XG, 189.0)}), None).run(
            "fake-sheet", str(CD_MP3), settings)
        self.assertEqual(result.output_path.parent, wanted)

    def test_folder_that_cant_be_created_stops_before_anything(self):
        blocker = self.workspace / "a file"
        blocker.write_text("not a folder")
        media = FakeMedia({"fx://xg": (XG, 189.0)})
        settings = Settings(output=OutputSettings(directory=str(blocker / "out")),
                            processing=ProcessingSettings(audio_only=True))
        with self.assertRaisesRegex(LarbError, r"Can't create the output folder .*a file"):
            self.pipeline(media, None).run("fake-sheet", str(CD_MP3), settings)
        self.assertEqual((media.lookups, media.downloads), (0, 0))

    def test_ensure_folder_names_the_folder(self):
        blocker = self.workspace / "blocker"
        blocker.write_text("x")
        with self.assertRaisesRegex(LarbError, "cache folder"):
            ensure_folder(blocker, "cache")


if __name__ == "__main__":
    unittest.main()
