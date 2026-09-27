"""Cache naming and lookup (naming rule documented for operators in HANDOFF.md)."""

from pathlib import Path

from larb.core.models import MediaKind

# Leftovers of an interrupted download: never count them as cached.
_PARTIAL_SUFFIXES = {".part", ".ytdl", ".tmp", ".temp"}


def cache_stem(media_id: str, kind: MediaKind) -> str:
    """File name without extension, e.g. "oKBwWQI-IoI_audio" or "oKBwWQI-IoI_v720".

    No title or artist in the name, so fixing a typo in the sheet doesn't cause a
    re-download. Audio and video files differ by the suffix, so one never stands
    in for the other.
    """
    return f"{media_id}_{kind.cache_suffix}"


def find_cached(cache_dir: Path, stem: str) -> Path | None:
    """Return the cached file for this stem, or None.

    Only an exact "<stem>.<ext>" counts. That skips partial downloads and a
    downloader's in-between pieces such as "<stem>.f136.mp4".
    """
    if not cache_dir.is_dir():
        return None
    for path in cache_dir.iterdir():
        if (path.is_file() and path.stem == stem and path.suffix
                and path.suffix.lower() not in _PARTIAL_SUFFIXES and path.stat().st_size > 0):
            return path
    return None
