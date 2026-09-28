"""Finding FFmpeg: static-ffmpeg (inside the venv) first, then a system FFmpeg (SPEC §6, TECH §3)."""

import contextlib
import io
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from larb.adapters.ffmpeg.helper import run_tool
from larb.core.errors import MediaToolMissingError

# 7.1 is where "-/filter_complex <file>" appeared, which the renderer needs (the graph is
# too long for the command line). Older versions are refused with a clear message instead
# of keeping an untested fallback (maintainer decision, TECH §3). xfade itself needs 4.3.
MIN_VERSION = (7, 1)


@dataclass(frozen=True)
class FfmpegTools:
    ffmpeg: Path
    ffprobe: Path
    origin: str                    # "static-ffmpeg" or "system"
    version_text: str              # e.g. "8.0.1-essentials_build-www.gyan.dev"
    version: tuple[int, int] | None  # None when the version string can't be parsed (dev builds)


def _read_version(ffmpeg: Path) -> tuple[str, tuple[int, int] | None]:
    first_line = run_tool(ffmpeg, ["-hide_banner", "-version"]).stdout.splitlines()[0]
    text = first_line.split("version", 1)[-1].split("Copyright")[0].strip()
    match = re.match(r"n?(\d+)\.(\d+)", text)
    return text, (int(match.group(1)), int(match.group(2))) if match else None


def _new_enough(version: tuple[int, int] | None) -> bool:
    # None = the version text has no number (development builds such as "N-12345-g...").
    # Those are built from current FFmpeg sources, so they are accepted; if one ever lacks
    # a feature, FFmpeg itself fails loudly and the run stops with a RenderError.
    return version is None or version >= MIN_VERSION


def fetch_static() -> tuple[Path, Path]:
    """Download the static-ffmpeg binaries if they aren't there yet (~45 s, ~200 MB).

    Only setup_once calls this (through tools/env_setup.py), showing the download
    progress. A run never downloads: it uses `_static()` (TECH §3).
    """
    from static_ffmpeg import run  # imported here: only this adapter may know about it
    ffmpeg, ffprobe = run.get_or_fetch_platform_executables_else_raise()
    return Path(ffmpeg), Path(ffprobe)


def _static() -> tuple[Path, Path]:
    """The static-ffmpeg binaries, only if setup_once has already downloaded them."""
    from static_ffmpeg import run  # imported here: only this adapter may know about it
    # static-ffmpeg writes this file when its download is complete. Without it, the call
    # below would start the download, which is setup_once's job, not a run's.
    if not (Path(run.get_platform_dir()) / "installed.crumb").exists():
        raise FileNotFoundError("binaries not downloaded (setup_once downloads them)")
    # With the download complete, this only returns the paths (and fixes permissions on
    # Linux/Mac). It prints nothing then, but keep its stdout out of our console anyway.
    with contextlib.redirect_stdout(io.StringIO()):
        ffmpeg, ffprobe = run.get_or_fetch_platform_executables_else_raise()
    return Path(ffmpeg), Path(ffprobe)


def find_ffmpeg() -> FfmpegTools:
    """Return FFmpeg and ffprobe, preferring the pinned static-ffmpeg binaries.

    Raises:
        MediaToolMissingError: Neither static-ffmpeg nor a system FFmpeg of at least
            MIN_VERSION works.
    """
    problems = []
    try:
        ffmpeg, ffprobe = _static()
        text, version = _read_version(ffmpeg)
    except Exception as e:  # any failure here just means "try the system one"
        problems.append(f"static-ffmpeg: {e}")
    else:
        if _new_enough(version):
            return FfmpegTools(ffmpeg, ffprobe, "static-ffmpeg", text, version)
        problems.append(f"static-ffmpeg {text} is too old")

    # shutil.which only *finds* the system binary; it is still called by full path.
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        text, version = _read_version(Path(ffmpeg))
        if _new_enough(version):
            return FfmpegTools(Path(ffmpeg), Path(ffprobe), "system", text, version)
        problems.append(f"system FFmpeg {text} ({ffmpeg}) is too old")
    else:
        problems.append("no system FFmpeg found")
    needed = f"{MIN_VERSION[0]}.{MIN_VERSION[1]}"
    raise MediaToolMissingError(f"No usable FFmpeg: version {needed} or newer is needed. "
                                "Run setup_once again, or update the system FFmpeg.\n  - "
                                + "\n  - ".join(problems))
