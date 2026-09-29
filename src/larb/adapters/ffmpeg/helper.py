"""The single place where FFmpeg and ffprobe are run (CLAUDE.md: no ad-hoc subprocess calls).

The binary path is always passed in explicitly and kept separate from the
argument list, so swapping static <-> system FFmpeg touches nothing else.
Never rely on `ffmpeg` being on PATH.
"""

import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from larb.core.errors import MediaToolMissingError, RenderError, StoppedError

STDERR_TAIL_CHARS = 2000  # how much of FFmpeg's error output to put in an error message
POLL_S = 0.1              # how often a running tool checks whether it should stop
QUIT_GRACE_S = 5.0        # after "q", how long FFmpeg gets to close its output before it's killed


def run_tool(binary: Path, args: list[str], on_command: Callable[[str], None] | None = None,
             check: bool = True, stop: threading.Event | None = None) -> subprocess.CompletedProcess:
    """Run FFmpeg or ffprobe and return the finished process (stdout/stderr as text).

    Args:
        binary: Full path of the executable.
        args: Arguments only, one list element each (never a shell string).
        on_command: Called with the exact command line, ready to paste into a
            terminal to reproduce the run.
        check: Raise RenderError on a non-zero exit code.
        stop: When set, the tool is asked to quit ("q" on its input, which lets FFmpeg
            close its output file properly), and killed if it's still running after
            QUIT_GRACE_S. Set before the call, the tool isn't started at all.

    Raises:
        MediaToolMissingError: The binary can't be started.
        RenderError: The tool exited with an error (only when check is True).
        StoppedError: `stop` was set while the tool ran (or before).
    """
    if stop is not None and stop.is_set():
        raise StoppedError("Stopped")
    cmd = [str(binary), *args]
    if on_command:
        on_command(subprocess.list2cmdline(cmd))
    try:
        # Decode as UTF-8 explicitly: the Windows console codepage (e.g. cp874 on a
        # Thai system) would garble file names and FFmpeg's messages otherwise.
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        raise MediaToolMissingError(f"Can't start {binary}: {e}") from None

    # Both pipes are read on their own threads: FFmpeg blocks if either one fills up.
    # (communicate() would close stdin, and "q" couldn't be sent any more.)
    out: list[str] = []
    err: list[str] = []
    readers = [threading.Thread(target=lambda s=s, into=into: into.append(s.read()), daemon=True)
               for s, into in ((proc.stdout, out), (proc.stderr, err))]
    for reader in readers:
        reader.start()

    stopped = False
    while True:
        try:
            proc.wait(timeout=POLL_S)
            break
        except subprocess.TimeoutExpired:
            pass
        if stop is not None and stop.is_set() and not stopped:
            stopped = True
            _ask_to_quit(proc)
    for reader in readers:
        reader.join()
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        try:
            pipe.close()
        except OSError:
            pass   # stdin: FFmpeg may have quit before reading the "q"
    if stopped:
        raise StoppedError("Stopped")

    result = subprocess.CompletedProcess(cmd, proc.returncode, "".join(out), "".join(err))
    if check and result.returncode != 0:
        tail = result.stderr[-STDERR_TAIL_CHARS:].strip()
        raise RenderError(f"{Path(binary).name} failed (exit code {result.returncode}):\n{tail}")
    return result


def _ask_to_quit(proc: subprocess.Popen) -> None:
    """FFmpeg quits cleanly on "q" (its output stays playable); kill it if it doesn't."""
    try:
        proc.stdin.write("q\n")
        proc.stdin.flush()
    except OSError:
        pass   # it has just exited, or doesn't read its input (ffprobe)
    try:
        proc.wait(timeout=QUIT_GRACE_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
