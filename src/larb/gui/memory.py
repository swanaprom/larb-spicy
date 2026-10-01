"""Remembered inputs (GUI.md 1.1, 1.4): the Sheet and Countdown fields as they were at
the last Run, filled in again when the window opens.

They live in their own small file, config/last_inputs.toml: what one run used, not
settings, so they're kept apart from config.toml. Clear cache never touches it.

The row range is deliberately NOT remembered: a remembered range could silently cut
the next run short.

Remembering never gets in the way: a missing, unreadable or odd file just means
empty fields, and a remembered file that's gone is left for Run to report as usual.
"""

import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

import tomli_w

from larb.adapters.toml_settings import atomic_write
from larb.core.errors import ConfigError


@dataclass(frozen=True)
class LastInputs:
    sheet: str = ""
    countdown: str = ""   # "" = the default countdown


def load_last_inputs(path: Path) -> LastInputs:
    """What was remembered; empty fields if there's nothing usable. Never raises."""
    try:
        # utf-8-sig: in case someone saves it from Notepad (TECH §5).
        doc = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return LastInputs()
    return LastInputs(**{key: value for key in ("sheet", "countdown")
                         if isinstance(value := doc.get(key), str)})


def save_last_inputs(path: Path, inputs: LastInputs) -> str | None:
    """Remember the inputs (atomically). Returns why it failed, or None.

    A failure must never stop a run, so it's reported, not raised.
    """
    try:
        atomic_write(path, tomli_w.dumps(asdict(inputs)))
    except ConfigError as e:
        return str(e)
    return None
