"""MediaSource implemented with yt-dlp (recipes: TECH §9).

A new YoutubeDL instance is created for every call, so parallel downloads
never share state.
"""

from pathlib import Path

import yt_dlp

from larb.core.errors import DownloadError, MediaUnavailableError
from larb.core.models import MediaInfo, MediaKind
from larb.core.ports import MediaSource

# Messages that mean "this video will never download"; anything else is worth a retry
# (e.g. YouTube's intermittent "HTTP Error 403: Forbidden", ~1 in 10 video downloads
# without a JS runtime; one retry fixed 19 of 20 in the spike, TECH §9).
_PERMANENT_MARKERS = ("video unavailable", "this video is unavailable", "private video",
                      "has been removed", "copyright", "incomplete youtube id",
                      "sign in to confirm your age", "not available in your country")


def _is_permanent(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _PERMANENT_MARKERS)


def version() -> str:
    """yt-dlp's version: the first suspect when downloads break, so it's logged every run."""
    return yt_dlp.version.__version__


class YtDlpMediaSource(MediaSource):
    """Args:
        ffmpeg_dir: Folder holding the FFmpeg that yt-dlp should use for merging.
            Passed explicitly, or yt-dlp would pick whatever ffmpeg is on PATH.
    """

    def __init__(self, ffmpeg_dir: Path) -> None:
        self._ffmpeg_dir = ffmpeg_dir

    def _base_options(self) -> dict:
        return {
            "quiet": True,
            "no_warnings": True,     # hides the "no JS runtime" deprecation notice on every call
            "noprogress": True,
            "noplaylist": True,      # sheet URLs often carry "&list=RDMM..."
            "ffmpeg_location": str(self._ffmpeg_dir),
        }

    def lookup(self, url: str) -> MediaInfo:
        options = {**self._base_options(), "skip_download": True}
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise MediaUnavailableError(_clean(e)) from None
        if not info or info.get("_type") == "playlist":
            raise MediaUnavailableError(f"{url} is not a single video")
        if info.get("duration") is None:
            raise MediaUnavailableError(f"{url} has no length (a live stream?)")
        return MediaInfo(media_id=info["id"], title=info.get("title") or "",
                         duration_s=float(info["duration"]))

    def download(self, url: str, kind: MediaKind, dest_dir: Path, stem: str) -> Path:
        options = {**self._base_options(), "outtmpl": str(dest_dir / f"{stem}.%(ext)s")}
        if kind.audio_only:
            options["format"] = "ba/b"
        else:
            # A sort, not a filter: prefers H.264 up to max_height, and still falls
            # back to something when no H.264 exists. H.264 renders ~2.4x faster
            # than AV1 (TECH §9). Hard-coded, not a setting (SPEC §7).
            options["format_sort"] = ["vcodec:h264", f"res:{kind.max_height}", "acodec:m4a"]
        try:
            with yt_dlp.YoutubeDL(options) as ydl:  # fresh instance per call
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            message = _clean(e)
            raise DownloadError(message, retryable=not _is_permanent(message)) from None
        try:
            path = Path(info["requested_downloads"][0]["filepath"])
        except (KeyError, IndexError, TypeError):
            raise DownloadError(f"yt-dlp didn't report a file for {url}", retryable=True) from None
        if not path.is_file():
            raise DownloadError(f"downloaded file is missing: {path}", retryable=True)
        return path


def _clean(error: Exception) -> str:
    """yt-dlp messages start with "ERROR: [youtube] <id>: "; keep the readable part."""
    message = str(error)
    return message.removeprefix("ERROR: ").strip()
