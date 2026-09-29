"""MediaSource implemented with yt-dlp (recipes: TECH §9).

A new YoutubeDL instance is created for every call, so parallel look-ups and
downloads never share state.

Each video is looked up once: `lookup` remembers what it found, and `download`
reuses it instead of asking YouTube again (TECH §14). If the remembered info is
too old or the download with it fails, `download` falls back to a fresh look-up
and logs that it did.
"""

import threading
import time
from pathlib import Path

import yt_dlp

from larb.core.errors import DownloadError, MediaUnavailableError, StoppedError
from larb.core.models import Level, LogEvent, MediaInfo, MediaKind
from larb.core.ports import EventSink, MediaSource

# Messages that mean "this video will never download"; anything else is worth a retry
# (e.g. YouTube's intermittent "HTTP Error 403: Forbidden", ~1 in 10 video downloads
# without a JS runtime; one retry fixed 19 of 20 in the spike, TECH §9).
_PERMANENT_MARKERS = ("video unavailable", "this video is unavailable", "private video",
                      "has been removed", "copyright", "incomplete youtube id",
                      "sign in to confirm your age", "not available in your country")

# YouTube's download links in the looked-up info expire after about 6 hours. Remembered
# info older than this is not reused; the download looks the video up again instead.
REMEMBER_FOR_S = 60 * 60

# Parts of the looked-up info that downloads never use. Automatic captions are ~80 % of
# it (~0.4 MB per video), so dropping them keeps 300 remembered videos at ~20 MB.
_UNUSED_INFO_KEYS = ("automatic_captions", "subtitles", "heatmap")

# A sheet URL with "&list=..." first resolves to a link to the video itself (TECH §14).
_MAX_REDIRECTS = 3


def _is_permanent(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _PERMANENT_MARKERS)


class _SilentLogger:
    """yt-dlp prints its errors on stderr even with quiet=True. They're already turned
    into our own errors (and logged by the core), so drop yt-dlp's copy."""

    def debug(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass


def version() -> str:
    """yt-dlp's version: the first suspect when downloads break, so it's logged every run."""
    return yt_dlp.version.__version__


class YtDlpMediaSource(MediaSource):
    """Args:
        ffmpeg_dir: Folder holding the FFmpeg that yt-dlp should use for merging.
            Passed explicitly, or yt-dlp would pick whatever ffmpeg is on PATH.
        events: Where to log look-up times (DEBUG) and fresh look-ups at download (INFO).
    """

    def __init__(self, ffmpeg_dir: Path, events: EventSink) -> None:
        self._ffmpeg_dir = ffmpeg_dir
        self._events = events
        self._lock = threading.Lock()   # look-ups and downloads run in several threads
        self._stop = threading.Event()  # set by cancel()
        self._remembered: dict[str, tuple[float, dict]] = {}   # url -> (when, raw info)

    def cancel(self) -> None:
        # Downloads notice it in their progress hook (several times a second while
        # data arrives). A look-up can't be interrupted; it finishes first.
        self._stop.set()

    def _raise_if_stopped(self) -> None:
        if self._stop.is_set():
            raise StoppedError("Stopped")

    def _stop_hook(self, _status: dict) -> None:
        """yt-dlp calls this while downloading and around merging. DownloadCancelled is
        yt-dlp's own "stop now" exception: it isn't wrapped or retried inside yt-dlp."""
        if self._stop.is_set():
            raise yt_dlp.utils.DownloadCancelled("Stopped")

    def _base_options(self) -> dict:
        return {
            "quiet": True,
            "logger": _SilentLogger(),
            "no_warnings": True,     # hides the "no JS runtime" deprecation notice on every call
            "noprogress": True,
            "noplaylist": True,      # sheet URLs often carry "&list=RDMM..."
            "ffmpeg_location": str(self._ffmpeg_dir),
        }

    def _log(self, level: Level, message: str) -> None:
        self._events.emit(LogEvent(level, "media", message))

    def lookup(self, url: str) -> MediaInfo:
        self._raise_if_stopped()
        started = time.perf_counter()
        options = {**self._base_options(), "skip_download": True}
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                # process=False: the raw info, before any format is picked. Only this can be
                # reused by the download: info processed by another YoutubeDL got HTTP 403
                # on every audio download tried (8 of 8, TECH §14).
                info = ydl.extract_info(url, download=False, process=False)
                for _ in range(_MAX_REDIRECTS):
                    if not info or info.get("_type") != "url":
                        break
                    info = ydl.extract_info(info["url"], download=False, process=False,
                                            ie_key=info.get("ie_key"))
        except yt_dlp.utils.DownloadError as e:
            message = _clean(e)
            raise MediaUnavailableError(message, retryable=not _is_permanent(message)) from None
        if not info or info.get("_type") not in (None, "video"):
            raise MediaUnavailableError(f"{url} is not a single video")
        if info.get("duration") is None:
            raise MediaUnavailableError(f"{url} has no length (a live stream?)")
        for key in _UNUSED_INFO_KEYS:
            info.pop(key, None)
        with self._lock:
            self._remembered[url] = (time.monotonic(), info)
        self._log(Level.DEBUG, f"looked up {info['id']} in {time.perf_counter() - started:.1f} s")
        return MediaInfo(media_id=info["id"], title=info.get("title") or "",
                         duration_s=float(info["duration"]))

    def _take_remembered(self, url: str) -> dict | None:
        """The info remembered by lookup(url), used once, or None if there is none or it's too old."""
        with self._lock:
            when, info = self._remembered.pop(url, (0.0, None))
        if info is None:
            self._log(Level.INFO, f"no looked-up info for {url}; looking it up again")
            return None
        age = time.monotonic() - when
        if age > REMEMBER_FOR_S:
            self._log(Level.INFO, f"looked-up info for {info['id']} is {age / 60:.0f} min old "
                      f"(links may have expired); looking it up again")
            return None
        return info

    def download(self, url: str, kind: MediaKind, dest_dir: Path, stem: str) -> Path:
        self._raise_if_stopped()
        options = {**self._base_options(), "outtmpl": str(dest_dir / f"{stem}.%(ext)s"),
                   "progress_hooks": [self._stop_hook], "postprocessor_hooks": [self._stop_hook]}
        if kind.audio_only:
            options["format"] = "ba/b"
        else:
            # A sort, not a filter: prefers H.264 up to max_height, and still falls
            # back to something when no H.264 exists. H.264 renders ~2.4x faster
            # than AV1 (TECH §9). Hard-coded, not a setting (SPEC §7).
            options["format_sort"] = ["vcodec:h264", f"res:{kind.max_height}", "acodec:m4a"]
        info = self._take_remembered(url)
        if info is not None:
            self._log(Level.DEBUG, f"downloading {info['id']} with the looked-up info")
            try:
                return self._download(url, options, lambda ydl: ydl.process_ie_result(info, download=True))
            except DownloadError as e:
                if not e.retryable or self._stop.is_set():
                    raise
                # A retry with fresh info is what fixes YouTube's intermittent 403 (TECH §9).
                self._log(Level.INFO, f"download of {info['id']} with the looked-up info failed "
                          f"({e}); looking it up again")
        return self._download(url, options, lambda ydl: ydl.extract_info(url, download=True))

    def _download(self, url: str, options: dict, fetch) -> Path:
        """Run one download with a fresh YoutubeDL; `fetch(ydl)` returns yt-dlp's info."""
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = fetch(ydl)
        except Exception as e:
            # Whatever yt-dlp raised after a stop (DownloadCancelled from our hook, or an
            # error it caused), it's a stop. Leftover pieces are the caller's to remove.
            if self._stop.is_set():
                raise StoppedError("Stopped") from None
            if not isinstance(e, yt_dlp.utils.DownloadError):
                raise
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
