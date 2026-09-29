"""Command-line entry point: runs once, with the adapters wired by larb.app.

Usage (from the repository root, with the venv's Python):
    set PYTHONPATH=src            (Linux/Mac: export PYTHONPATH=src)
    python -m larb <sheet URL or CSV file> [--countdown FILE_OR_URL] [--rows 2-10] [--verbose]
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from larb import app
from larb.adapters.console_events import ConsoleEventSink
from larb.adapters.file_events import FileEventSink, MultiEventSink
from larb.core.cache import clear_cache
from larb.core.errors import LarbError
from larb.core.manifest import parse_row_range
from larb.core.models import Level, LogEvent
from larb.core.ports import EventSink


def _is_interactive() -> bool:
    """True when a person is at the terminal (not a test, a pipe or a scheduled job)."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def offer_cache_clear(cache_dir: Path, events: EventSink, interactive: bool,
                      ask: Callable[[str], str] = input) -> bool:
    """After a successful run, ask whether to clear the download cache (SPEC §10).

    Only asked when interactive, so tests and unattended runs never wait for an
    answer. The default (just Enter) is No. Returns True if the cache was cleared.
    """
    if not interactive:
        return False
    try:
        answer = ask("Clear the download cache? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer.strip().lower() in ("y", "yes"):
        deleted = clear_cache(cache_dir)
        events.emit(LogEvent(Level.INFO, "cache", f"Cache cleared: {deleted} file(s) deleted from {cache_dir}"))
        return True
    events.emit(LogEvent(Level.INFO, "cache", f"Cache kept: {cache_dir}"))
    return False


def main(argv: list[str] | None = None) -> int:
    # Print Thai text correctly on consoles with a non-UTF-8 codepage (e.g. cp874).
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="larb", description="Combine songs from a sheet "
                                     "into one video or audio file with countdowns in between.")
    parser.add_argument("source", help="Google Sheet URL, or path to a CSV file")
    parser.add_argument("--countdown", help="countdown: a video/audio file or a YouTube URL "
                        "(default: countdown.default_urls[0], then countdown.default_files[0])")
    parser.add_argument("--rows", help="only use these rows, numbered as in the sheet (row 1 is the "
                        "header), e.g. 2-10, or 5 for one row (default: all rows)")
    parser.add_argument("--verbose", action="store_true", help="also show every FFmpeg command "
                        "(the log file always has them)")
    args = parser.parse_args(argv)

    log_file = FileEventSink(app.LOG_DIR)
    events = MultiEventSink(ConsoleEventSink(Level.DEBUG if args.verbose else Level.INFO), log_file)
    try:
        events.emit(LogEvent(Level.INFO, "start", f"Log file: {log_file.path}"))
        rows = parse_row_range(args.rows) if args.rows is not None else None
        store = app.settings_store()
        settings = store.load()
        countdown = app.countdown_for_run(args.countdown, settings)
        run = app.build_run(store, events)
        events.emit(LogEvent(Level.INFO, "start", f"{run.tools_text}, settings: {app.CONFIG_FILE}"))
        result = run.pipeline.run(args.source, countdown, settings, rows=rows)
        events.emit(LogEvent(Level.INFO, "finished", f"{result.songs_rendered} song(s) -> {result.output_path} "
                             f"({result.row_errors} row error(s), {result.row_warnings} warning(s))"))
        offer_cache_clear(result.cache_dir, events, _is_interactive())
        return 0
    except LarbError as e:
        events.emit(LogEvent(Level.ERROR, "abort", str(e)))
        return 1
    finally:
        log_file.close()
