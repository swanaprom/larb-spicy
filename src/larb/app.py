"""Wiring: the only place that knows which adapter implements which port.

Both front ends use it, the command line (cli.py) and the window (gui/), so a run is
put together the same way whichever one starts it. One Pipeline is built per run.
"""

from dataclasses import dataclass
from pathlib import Path

from larb.adapters import ytdlp_media
from larb.adapters.ffmpeg.locate import find_ffmpeg
from larb.adapters.ffmpeg.processor import FfmpegProcessor
from larb.adapters.sheet_csv import CsvSongListSource
from larb.adapters.toml_settings import TomlSettingsStore
from larb.core.models import Settings
from larb.core.pipeline import Pipeline, choose_countdown, is_url
from larb.core.ports import EventSink
from larb.core.settings import resolve_folder

ROOT = Path(__file__).resolve().parents[2]      # the project folder
WORKSPACE = ROOT / "workspace"                  # default home of runtime files (cache, output, tmp)
LOG_DIR = WORKSPACE / "logs"                    # one log file per run, newest 5 kept
# Not in workspace/: that folder gets deleted to free space, and settings must survive it.
# config/config.toml is gitignored; config/example.toml is its committed template.
CONFIG_FILE = ROOT / "config" / "config.toml"
TEMPLATE_FILE = ROOT / "config" / "example.toml"


def settings_store() -> TomlSettingsStore:
    return TomlSettingsStore(CONFIG_FILE, TEMPLATE_FILE)


def countdown_for_run(given: str | None, settings: Settings) -> str:
    """The run's countdown (core.pipeline.choose_countdown), with a relative file
    looked for in the current folder, then in the project folder.

    Raises:
        LarbError: No countdown given and none set in the settings.
    """
    countdown = choose_countdown(given, settings)
    if is_url(countdown):
        return countdown
    path = Path(countdown)
    if not path.is_absolute():
        path = path.resolve() if path.exists() else ROOT / path
    return str(path)


def folder(setting: str, default_name: str) -> Path:
    """Where output.directory / download.cache_directory point (core.settings.resolve_folder)."""
    return resolve_folder(setting, default_name, ROOT, WORKSPACE)


@dataclass
class Run:
    """Everything one run needs, wired together."""

    pipeline: Pipeline
    tools_text: str     # "yt-dlp <version>", for the log at run start


def build_run(store: TomlSettingsStore, events: EventSink) -> Run:
    """New adapters and a new Pipeline for one run (a stopped run's adapters can't be reused).

    Raises:
        MediaToolMissingError: No usable FFmpeg.
        ConfigError: [sheet.columns] is invalid.
    """
    tools = find_ffmpeg()
    pipeline = Pipeline(
        songs=CsvSongListSource(store.sheet_columns()),
        media=ytdlp_media.YtDlpMediaSource(tools.ffmpeg.parent, events),
        processor=FfmpegProcessor(tools, WORKSPACE / "tmp", events),
        events=events,
        workspace=WORKSPACE,
        project_dir=ROOT,
    )
    return Run(pipeline, f"yt-dlp {ytdlp_media.version()}")
