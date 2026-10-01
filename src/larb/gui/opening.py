"""Open file / Open folder (GUI.md 2.4): the system's default app for the output, or
its file manager for the folder, and the reason when that fails.

Windows says at once (os.startfile raises). Linux and Mac hand the work to `xdg-open` /
`open`, which only say through their exit code and error output (e.g. "no media player
found" on a fresh Ubuntu, TECH §20), so they're waited for on a thread of their own.
"""

import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

# How long to wait for xdg-open / open to report. Still running after that = it's
# showing something (some desktops keep xdg-open running): treated as success.
WAIT_S = 30.0


@dataclass
class OpenAttempt:
    """One Open file / Open folder click. `done` is set once the outcome is known;
    `error` is then the system's reason, or None if it opened."""

    done: threading.Event = field(default_factory=threading.Event)
    error: str | None = None


def start_open(path: Path) -> OpenAttempt:
    """Ask the system to open `path`. Returns at once; watch the attempt's `done`."""
    attempt = OpenAttempt()
    if sys.platform == "win32":
        try:
            os.startfile(path)   # noqa: S606 - opening the operator's own output
        except OSError as e:
            attempt.error = e.strerror or str(e)
        attempt.done.set()
        return attempt
    command = ["open" if sys.platform == "darwin" else "xdg-open", str(path)]
    try:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True, errors="replace")
    except OSError as e:   # e.g. xdg-open itself isn't installed
        attempt.error = f"{command[0]}: {e.strerror or e}"
        attempt.done.set()
        return attempt
    threading.Thread(target=_wait_for, args=(proc, attempt), daemon=True).start()
    return attempt


def _wait_for(proc: subprocess.Popen, attempt: OpenAttempt) -> None:
    try:
        _, err = proc.communicate(timeout=WAIT_S)
        if proc.returncode != 0:
            lines = err.strip().splitlines()
            attempt.error = lines[-1] if lines else f"{proc.args[0]} failed (exit code {proc.returncode})"
    except subprocess.TimeoutExpired:
        pass
    finally:
        attempt.done.set()
