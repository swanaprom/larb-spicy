"""Validation of settings values. The file format is the adapter's job; the rules are here."""

from larb.core.errors import ConfigError
from larb.core.models import Settings


def validate_settings(settings: Settings) -> None:
    """Check every value and report all problems at once.

    Raises:
        ConfigError: One or more values are out of range. The message lists them all.
    """
    problems = []
    d, p = settings.download, settings.processing

    if d.max_parallel_downloads < 1:
        problems.append(f"download.max_parallel_downloads must be 1 or more (got {d.max_parallel_downloads})")
    if d.max_retries < 0:
        problems.append(f"download.max_retries must be 0 or more (got {d.max_retries})")
    if not 144 <= d.max_height <= 4320:
        problems.append(f"download.max_height must be between 144 and 4320 (got {d.max_height})")
    if d.max_height % 2:
        # Video encoders need even frame sizes.
        problems.append(f"download.max_height must be an even number (got {d.max_height})")
    if not 0 < p.crossfade_duration_seconds <= 10:
        problems.append("processing.crossfade_duration_seconds must be more than 0 and at most 10 "
                        f"(got {p.crossfade_duration_seconds})")

    if problems:
        raise ConfigError("Invalid settings:\n  - " + "\n  - ".join(problems))
