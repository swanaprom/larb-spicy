"""Validation of settings values, and the folder rule. The file format is the adapter's
job; the rules are here."""

import math
from pathlib import Path

from larb.core.errors import ConfigError, LarbError
from larb.core.models import DEFAULT_CROSSFADE_S, Settings

MAX_CROSSFADE_S = 10.0
# The smallest crossfade the GUI corrects to: 3 frames, the same floor as the shortest
# usable clip (SPEC §9 stage 6).
MIN_CROSSFADE_FIELD_S = 0.1


def validate_settings(settings: Settings) -> None:
    """Check every value and report all problems at once.

    Raises:
        ConfigError: One or more values are out of range. The message lists them all.
    """
    problems = []
    d, p = settings.download, settings.processing

    if d.max_parallel_downloads < 1:
        problems.append(f"download.max_parallel_downloads must be 1 or more (got {d.max_parallel_downloads})")
    if d.max_parallel_lookups < 1:
        problems.append(f"download.max_parallel_lookups must be 1 or more (got {d.max_parallel_lookups})")
    if d.max_retries < 0:
        problems.append(f"download.max_retries must be 0 or more (got {d.max_retries})")
    if not 144 <= d.max_height <= 4320:
        problems.append(f"download.max_height must be between 144 and 4320 (got {d.max_height})")
    if d.max_height % 2:
        # Video encoders need even frame sizes.
        problems.append(f"download.max_height must be an even number (got {d.max_height})")
    if not 0 < p.crossfade_duration_seconds <= MAX_CROSSFADE_S:
        problems.append("processing.crossfade_duration_seconds must be more than 0 and at most 10 "
                        f"(got {p.crossfade_duration_seconds})")

    if problems:
        raise ConfigError("Invalid settings:\n  - " + "\n  - ".join(problems))


def correct_crossfade(text: str) -> float:
    """The crossfade the GUI shows after the operator leaves the field (SPEC §7).

    Not a number (blank, spaces, letters, "nan") -> the default. 0 or less -> the
    3-frame floor. More than the maximum -> the maximum. Anything else is kept.
    """
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError:
        return DEFAULT_CROSSFADE_S
    if math.isnan(value):
        return DEFAULT_CROSSFADE_S
    if value <= 0:
        return MIN_CROSSFADE_FIELD_S
    return min(value, MAX_CROSSFADE_S)


def resolve_folder(setting: str, default_name: str, project_dir: Path, workspace: Path) -> Path:
    """Where a folder setting (output.directory, download.cache_directory) points.

    Empty = the default, workspace/<default_name>. A relative path starts in the
    project folder (the one holding config/ and workspace/), so "workspace/output"
    means what it says. An absolute path is used as it is.
    """
    if not setting.strip():
        return workspace / default_name
    path = Path(setting.strip())
    return path if path.is_absolute() else project_dir / path


def folder_setting(shown: str, default_name: str, project_dir: Path, workspace: Path) -> str:
    """What to save for a folder the GUI shows as a full path: "" when it is the
    default folder, so config.toml keeps working if the project folder moves."""
    if not shown.strip():
        return ""
    default = resolve_folder("", default_name, project_dir, workspace)
    chosen = resolve_folder(shown, default_name, project_dir, workspace)
    return "" if _same_path(chosen, default) else str(chosen)


def ensure_folder(path: Path, what: str) -> Path:
    """Create the folder if it's missing.

    Raises:
        LarbError: It can't be created (e.g. no permission), naming the folder.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise LarbError(f"Can't create the {what} folder {path}: {e.strerror or e}") from None
    if not path.is_dir():
        raise LarbError(f"The {what} folder {path} isn't a folder")
    return path


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b
