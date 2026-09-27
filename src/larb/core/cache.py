"""Cache naming, lookup and clearing (naming rule documented for operators in HANDOFF.md)."""

import re
from pathlib import Path

from larb.core.models import MediaKind

# Leftovers of an interrupted download: never count them as cached.
_PARTIAL_SUFFIXES = {".part", ".ytdl", ".tmp", ".temp"}

# A cache file, or a leftover piece of one: "<id>_audio.<...>" or "<id>_v<height>.<...>",
# e.g. "abc_audio.webm", "abc_v720.mp4", "abc_v720.f136.mp4.part".
_CACHE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+_(audio|v\d+)\..+$")


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


def clear_cache(cache_dir: Path) -> int:
    """Delete the cached downloads in cache_dir and return how many files were deleted.

    Only files named by the cache rule (plus leftovers of interrupted downloads)
    are deleted. The operator may point the cache at any folder, so anything
    else in it is left alone. Subfolders are never touched.
    """
    if not cache_dir.is_dir():
        return 0
    deleted = 0
    for path in cache_dir.iterdir():
        if path.is_file() and _CACHE_NAME_RE.match(path.name):
            path.unlink()
            deleted += 1
    return deleted
