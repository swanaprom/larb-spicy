"""Settings file: download.max_parallel_lookups (slice 2), loaded, saved and validated;
the crossfade default and the GUI's correction of the field (slice 5)."""

import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import ROOT  # noqa: E402
from larb.adapters.toml_settings import TomlSettingsStore  # noqa: E402
from larb.core.errors import ConfigError  # noqa: E402
from larb.core.models import Settings  # noqa: E402
from larb.core.settings import correct_crossfade, validate_settings  # noqa: E402

TEMPLATE = ROOT / "config" / "example.toml"


class LookupsSettingTest(unittest.TestCase):

    def setUp(self):
        (ROOT / "workspace").mkdir(exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix="test_", dir=ROOT / "workspace"))
        self.path = self.dir / "config.toml"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_default_is_5(self):
        settings = TomlSettingsStore(self.path, TEMPLATE).load()   # first run: copied from the template
        self.assertEqual(settings.download.max_parallel_lookups, 5)

    def test_older_file_without_the_key_gets_the_default(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        older = "\n".join(line for line in text.splitlines() if not line.startswith("max_parallel_lookups"))
        self.assertNotIn("max_parallel_lookups", older)
        self.path.write_text(older, encoding="utf-8")
        settings = TomlSettingsStore(self.path, TEMPLATE).load()
        self.assertEqual(settings.download.max_parallel_lookups, 5)
        self.assertEqual(settings.download.max_parallel_downloads, 3)   # the other key is untouched

    def test_saved_and_read_back(self):
        store = TomlSettingsStore(self.path, TEMPLATE)
        settings = store.load()
        changed = replace(settings, download=replace(settings.download, max_parallel_lookups=8))
        store.save(changed)
        self.assertEqual(TomlSettingsStore(self.path, TEMPLATE).load().download.max_parallel_lookups, 8)

    def test_must_be_at_least_1(self):
        settings = TomlSettingsStore(self.path, TEMPLATE).load()
        with self.assertRaisesRegex(ConfigError, "max_parallel_lookups must be 1 or more"):
            validate_settings(replace(settings, download=replace(settings.download, max_parallel_lookups=0)))


class CrossfadeTest(unittest.TestCase):
    def test_default_is_0_8(self):
        self.assertEqual(Settings().processing.crossfade_duration_seconds, 0.8)
        store_dir = Path(tempfile.mkdtemp(prefix="test_", dir=ROOT / "workspace"))
        try:
            loaded = TomlSettingsStore(store_dir / "config.toml", TEMPLATE).load()
            self.assertEqual(loaded.processing.crossfade_duration_seconds, 0.8)   # the template agrees
        finally:
            shutil.rmtree(store_dir, ignore_errors=True)

    def test_not_a_number_restores_the_default(self):
        for text in ("", "   ", "abc", "1s", "nan", "--1"):
            self.assertEqual(correct_crossfade(text), 0.8, msg=text)

    def test_zero_or_less_becomes_the_3_frame_floor(self):
        for text in ("0", "-1", "-0.5", " 0.0 "):
            self.assertEqual(correct_crossfade(text), 0.1, msg=text)

    def test_above_10_becomes_10(self):
        for text in ("10.5", "99", "inf"):
            self.assertEqual(correct_crossfade(text), 10.0, msg=text)

    def test_in_range_is_kept(self):
        for text, value in (("0.05", 0.05), ("1", 1.0), (" 2.5 ", 2.5), ("10", 10.0), ("1,5", 1.5)):
            self.assertEqual(correct_crossfade(text), value, msg=text)
            validate_settings(Settings())   # and the default itself is valid


if __name__ == "__main__":
    unittest.main()
