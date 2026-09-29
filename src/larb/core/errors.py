"""The project's own error types.

Every error that crosses a port is one of these, never a library's exception.
Adapters catch their tool's exceptions and re-raise one of these, so the core
(and later the GUI) only ever has to understand this one family.
"""


class LarbError(Exception):
    """Base class for every error this program raises on purpose."""


class ConfigError(LarbError):
    """The settings file is unreadable or holds an invalid value."""


class SongListError(LarbError):
    """The song list can't be read at all (unreachable, private, or a column header is missing).

    This aborts the run: without the list there is nothing to do.
    """


class MediaUnavailableError(LarbError):
    """A video can't be looked up. Becomes a row error (after retries, if retryable).

    Attributes:
        retryable: True when trying again might work (e.g. a network hiccup).
            False when it never will (the video doesn't exist, is private, ...).
    """

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class DownloadError(LarbError):
    """A download failed.

    Attributes:
        retryable: True when trying again might work (e.g. a network hiccup or
            YouTube's intermittent HTTP 403). False when it never will.
    """

    def __init__(self, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class MediaToolMissingError(LarbError):
    """The media tool (FFmpeg) can't be found. Aborts the run."""


class RenderError(LarbError):
    """Measuring or rendering failed, or the result doesn't match what was planned."""


class StoppedError(LarbError):
    """The operator stopped the run. Any port call may raise it once the adapter's
    cancel() was called; the pipeline then ends the run like a failed one (SPEC §9)."""
