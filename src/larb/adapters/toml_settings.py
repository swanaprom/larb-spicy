"""SettingsStore for a TOML file (recipes and Windows gotchas: TECH §5)."""

import copy
import os
import tempfile
import time
import tomllib
from pathlib import Path

import tomli_w

from larb.core.errors import ConfigError
from larb.core.models import (CountdownSettings, DownloadSettings, OutputSettings,
                              ProcessingSettings, Settings)
from larb.core.ports import SettingsStore

REPLACE_RETRIES = 5
REPLACE_PAUSE_S = 0.2


def _read_toml(path: Path) -> dict:
    try:
        # utf-8-sig: Notepad's "UTF-8 with BOM" breaks tomllib otherwise (TECH §5).
        # Not a typo, keep it.
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} isn't valid TOML: {e}") from None
    except OSError as e:
        raise ConfigError(f"Can't read {path}: {e}") from None


def _fill_missing(doc: dict, defaults: dict) -> dict:
    """Add keys missing from doc (e.g. added in a newer version) with their defaults."""
    merged = copy.deepcopy(doc)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(merged[key], dict):
            merged[key] = _fill_missing(merged[key], value)
    return merged


def atomic_write(path: Path, text: str) -> None:
    """Write via a temp file in the same folder + os.replace, so a crash never
    leaves a half-written file. Retries because Windows refuses the replace while
    another program has the file open ("Access is denied", TECH §5)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(REPLACE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == REPLACE_RETRIES - 1:
                    raise
                time.sleep(REPLACE_PAUSE_S)
    except OSError as e:
        raise ConfigError(f"Can't write {path}: {e}. Close any program that has it open.") from None
    finally:
        Path(tmp).unlink(missing_ok=True)


class TomlSettingsStore(SettingsStore):
    """Args:
        path: The operator's settings file, config/config.toml (deliberately not in
            workspace/, which gets deleted to free space).
        template: config/example.toml. Copied as-is on first run, so the new file
            keeps its explanatory comments; also the source of defaults for keys
            missing from an older file.
    """

    def __init__(self, path: Path, template: Path) -> None:
        self._path = path
        self._template = template
        self._doc: dict | None = None

    def load(self) -> Settings:
        if not self._path.exists():
            try:
                atomic_write(self._path, self._template.read_text(encoding="utf-8"))
            except OSError as e:
                raise ConfigError(f"Can't read the template {self._template}: {e}") from None
        self._doc = _fill_missing(_read_toml(self._path), _read_toml(self._template))
        return self._to_settings(self._doc)

    def save(self, settings: Settings) -> None:
        # Start from the loaded file so keys the core doesn't model ([sheet.columns])
        # are kept. Comments are dropped by any TOML writer (TECH §5).
        doc = copy.deepcopy(self._doc) if self._doc else _read_toml(self._template)
        doc.setdefault("output", {}).update(directory=settings.output.directory,
                                            filename_template=settings.output.filename_template)
        doc.setdefault("countdown", {}).update(default_urls=list(settings.countdown.default_urls),
                                               default_files=list(settings.countdown.default_files))
        d = settings.download
        doc.setdefault("download", {}).update(cache_directory=d.cache_directory,
                                              max_parallel_downloads=d.max_parallel_downloads,
                                              max_retries=d.max_retries, max_height=d.max_height,
                                              max_parallel_lookups=d.max_parallel_lookups)
        p = settings.processing
        doc.setdefault("processing", {}).update(audio_only=p.audio_only, mirror=p.mirror,
                                                crossfade_duration_seconds=p.crossfade_duration_seconds)
        atomic_write(self._path, tomli_w.dumps(doc))
        self._doc = doc

    def sheet_columns(self) -> dict[str, str]:
        """[sheet.columns], for the sheet adapter only (the core never sees column names)."""
        if self._doc is None:
            self.load()
        columns = self._doc.get("sheet", {}).get("columns", {})
        if not isinstance(columns, dict) or not all(isinstance(v, str) for v in columns.values()):
            raise ConfigError("[sheet.columns] must map each field to a column header text")
        return dict(columns)

    # -- conversion with type checks -------------------------------------------

    def _to_settings(self, doc: dict) -> Settings:
        def get(table: str, key: str, kind: type):
            value = doc.get(table, {}).get(key)
            ok = (isinstance(value, bool) if kind is bool else
                  isinstance(value, (int, float)) and not isinstance(value, bool) if kind is float else
                  isinstance(value, int) and not isinstance(value, bool) if kind is int else
                  isinstance(value, list) and all(isinstance(v, str) for v in value) if kind is list else
                  isinstance(value, kind))
            if not ok:
                expected = {bool: "true or false", int: "a whole number", float: "a number",
                            str: "text in quotes", list: "a list of texts"}[kind]
                raise ConfigError(f"{self._path}: [{table}] {key} must be {expected} (got {value!r})")
            return tuple(value) if kind is list else float(value) if kind is float else value

        return Settings(
            output=OutputSettings(get("output", "directory", str), get("output", "filename_template", str)),
            countdown=CountdownSettings(get("countdown", "default_urls", list),
                                        get("countdown", "default_files", list)),
            download=DownloadSettings(get("download", "cache_directory", str),
                                      get("download", "max_parallel_downloads", int),
                                      get("download", "max_retries", int),
                                      get("download", "max_height", int),
                                      max_parallel_lookups=get("download", "max_parallel_lookups", int)),
            processing=ProcessingSettings(get("processing", "audio_only", bool),
                                          get("processing", "mirror", bool),
                                          get("processing", "crossfade_duration_seconds", float)),
        )
