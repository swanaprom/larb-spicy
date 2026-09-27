"""Finding FFmpeg: static-ffmpeg (inside the venv) first, then a system FFmpeg (SPEC §6, TECH §3)."""

import contextlib
import io
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from larb.adapters.ffmpeg.helper import run_tool
from larb.core.errors import MediaToolMissingError

MIN_VERSION = (4, 3)  # xfade was added in FFmpeg 4.3


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


def _static() -> tuple[Path, Path]:
    from static_ffmpeg import run  # imported here: only this adapter may know about it
    # static-ffmpeg prints download progress on stdout; keep it out of our console.
    # It fetches binaries on first use (~45 s, ~200 MB); setup_once should trigger that (SPEC §16).
    with contextlib.redirect_stdout(io.StringIO()):
        ffmpeg, ffprobe = run.get_or_fetch_platform_executables_else_raise()
    return Path(ffmpeg), Path(ffprobe)


def find_ffmpeg() -> FfmpegTools:
    """Return FFmpeg and ffprobe, preferring the pinned static-ffmpeg binaries.

    Raises:
        MediaToolMissingError: Neither static-ffmpeg nor a new-enough system FFmpeg works.
    """
    problems = []
    try:
        ffmpeg, ffprobe = _static()
        text, version = _read_version(ffmpeg)
        return FfmpegTools(ffmpeg, ffprobe, "static-ffmpeg", text, version)
    except Exception as e:  # any failure here just means "try the system one"
        problems.append(f"static-ffmpeg: {e}")

    # shutil.which only *finds* the system binary; it is still called by full path.
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        text, version = _read_version(Path(ffmpeg))
        if version is None or version >= MIN_VERSION:
            return FfmpegTools(Path(ffmpeg), Path(ffprobe), "system", text, version)
        problems.append(f"system FFmpeg {text} is older than {MIN_VERSION[0]}.{MIN_VERSION[1]}")
    else:
        problems.append("no system FFmpeg found")
    raise MediaToolMissingError("FFmpeg not found. Run setup_once again.\n  - " + "\n  - ".join(problems))
