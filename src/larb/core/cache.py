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


def _cache_files(cache_dir: Path) -> list[Path]:
    """The files in cache_dir named by the cache rule (plus leftovers of interrupted
    downloads). The operator may point the cache at any folder, so nothing else in
    it ever counts. Subfolders are never included."""
    if not cache_dir.is_dir():
        return []
    return [path for path in cache_dir.iterdir() if path.is_file() and _CACHE_NAME_RE.match(path.name)]


def cache_summary(cache_dir: Path) -> tuple[int, int]:
    """How many files clear_cache would delete, and their total size in bytes."""
    files = _cache_files(cache_dir)
    return len(files), sum(path.stat().st_size for path in files)


def clear_cache(cache_dir: Path) -> int:
    """Delete the cached downloads in cache_dir and return how many files were deleted.

    Only files named by the cache rule (plus leftovers of interrupted downloads)
    are deleted; see _cache_files.
    """
    files = _cache_files(cache_dir)
    for path in files:
        path.unlink()
    return len(files)


def remove_leftovers(cache_dir: Path, stem: str) -> list[Path]:
    """Delete what an interrupted download of `stem` left behind and return it.

    Only for a download that did not finish: every "<stem>.<...>" file is a piece
    of it (e.g. "<stem>.webm.part", "<stem>.f136.mp4"). A file another program
    still holds open is skipped.
    """
    removed = []
    for path in _cache_files(cache_dir):
        if path.name.startswith(f"{stem}."):
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                pass
    return removed
