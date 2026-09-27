"""Command-line entry point: builds the adapters, plugs them into the core, runs once.

This is the only place that knows which adapter implements which port.

Usage (from the repository root, with the venv's Python):
    set PYTHONPATH=src            (Linux/Mac: export PYTHONPATH=src)
    python -m larb <sheet URL or CSV file> [--countdown FILE] [--verbose]
"""

import argparse
import sys
from pathlib import Path

from larb.adapters import ytdlp_media
from larb.adapters.console_events import ConsoleEventSink
from larb.adapters.ffmpeg.locate import find_ffmpeg
from larb.adapters.ffmpeg.processor import FfmpegProcessor
from larb.adapters.sheet_csv import CsvSongListSource
from larb.adapters.toml_settings import TomlSettingsStore
from larb.core.errors import LarbError
from larb.core.models import Level, LogEvent
from larb.core.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]      # the repository folder
WORKSPACE = ROOT / "workspace"                  # default home of runtime files (cache, output, tmp)
# Not in workspace/: that folder gets deleted to free space, and settings must survive it.
# config/config.toml is gitignored; config/example.toml is its committed template.
CONFIG_FILE = ROOT / "config" / "config.toml"
TEMPLATE_FILE = ROOT / "config" / "example.toml"


def main(argv: list[str] | None = None) -> int:
    # Print Thai text correctly on consoles with a non-UTF-8 codepage (e.g. cp874).
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="larb", description="Combine songs from a sheet "
                                     "into one video or audio file with countdowns in between.")
    parser.add_argument("source", help="Google Sheet URL, or path to a CSV file")
    parser.add_argument("--countdown", type=Path,
                        help="countdown video/audio file (default: countdown.default_files[0])")
    parser.add_argument("--verbose", action="store_true", help="also show every FFmpeg command")
    args = parser.parse_args(argv)

    events = ConsoleEventSink(Level.DEBUG if args.verbose else Level.INFO)
    try:
        store = TomlSettingsStore(CONFIG_FILE, TEMPLATE_FILE)
        settings = store.load()
        countdown = args.countdown or (Path(settings.countdown.default_files[0])
                                       if settings.countdown.default_files else None)
        if countdown is None:
            raise LarbError(f"No countdown file. Pass --countdown FILE, or set countdown.default_files "
                            f"in {CONFIG_FILE}")
        if not countdown.is_absolute():
            countdown = (ROOT / countdown) if not countdown.exists() else countdown.resolve()

        tools = find_ffmpeg()
        events.emit(LogEvent(Level.INFO, "start", f"yt-dlp {ytdlp_media.version()}, settings: {CONFIG_FILE}"))
        pipeline = Pipeline(
            songs=CsvSongListSource(store.sheet_columns()),
            media=ytdlp_media.YtDlpMediaSource(tools.ffmpeg.parent),
            processor=FfmpegProcessor(tools, WORKSPACE / "tmp", events),
            events=events,
            workspace=WORKSPACE,
        )
        result = pipeline.run(args.source, countdown, settings)
    except LarbError as e:
        events.emit(LogEvent(Level.ERROR, "abort", str(e)))
        return 1
    events.emit(LogEvent(Level.INFO, "finished", f"{result.songs_rendered} song(s) -> {result.output_path} "
                         f"({result.row_errors} row error(s), {result.row_warnings} warning(s))"))
    return 0
