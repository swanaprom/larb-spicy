"""The single place where FFmpeg and ffprobe are run (CLAUDE.md: no ad-hoc subprocess calls).

The binary path is always passed in explicitly and kept separate from the
argument list, so swapping static <-> system FFmpeg touches nothing else.
Never rely on `ffmpeg` being on PATH.
"""

import subprocess
from collections.abc import Callable
from pathlib import Path

from larb.core.errors import MediaToolMissingError, RenderError

STDERR_TAIL_CHARS = 2000  # how much of FFmpeg's error output to put in an error message


def run_tool(binary: Path, args: list[str], on_command: Callable[[str], None] | None = None,
             check: bool = True) -> subprocess.CompletedProcess:
    """Run FFmpeg or ffprobe and return the finished process (stdout/stderr as text).

    Args:
        binary: Full path of the executable.
        args: Arguments only, one list element each (never a shell string).
        on_command: Called with the exact command line, ready to paste into a
            terminal to reproduce the run.
        check: Raise RenderError on a non-zero exit code.

    Raises:
        MediaToolMissingError: The binary can't be started.
        RenderError: The tool exited with an error (only when check is True).
    """
    cmd = [str(binary), *args]
    if on_command:
        on_command(subprocess.list2cmdline(cmd))
    try:
        # Decode as UTF-8 explicitly: the Windows console codepage (e.g. cp874 on a
        # Thai system) would garble file names and FFmpeg's messages otherwise.
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        raise MediaToolMissingError(f"Can't start {binary}: {e}") from None
    if check and proc.returncode != 0:
        tail = proc.stderr[-STDERR_TAIL_CHARS:].strip()
        raise RenderError(f"{Path(binary).name} failed (exit code {proc.returncode}):\n{tail}")
    return proc
