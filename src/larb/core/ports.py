"""Ports: what the core needs from the outside world.

Ports belong to the core and speak its language. Each one could be implemented
with a completely different tool; nothing here mentions yt-dlp, FFmpeg or Google.
Adapters (in larb.adapters) implement them. Approved by the maintainer; don't
change a signature without asking (CLAUDE.md).
"""

from abc import ABC, abstractmethod
from pathlib import Path

from larb.core.models import (ClipInfo, LogEvent, MediaInfo, MediaKind, RenderPlan,
                              Settings, SheetRow)


class SettingsStore(ABC):
    """Reads and writes the settings file."""

    @abstractmethod
    def load(self) -> Settings:
        """Return the settings, writing the defaults first if no settings file exists.

        Raises:
            ConfigError: The file can't be read or holds an invalid value.
        """

    @abstractmethod
    def save(self, settings: Settings) -> None:
        """Write the settings atomically (a crash never leaves a half-written file).

        Raises:
            ConfigError: The file can't be written.
        """


class SongListSource(ABC):
    """Provides the rows of the song list."""

    @abstractmethod
    def fetch_rows(self, source: str) -> list[SheetRow]:
        """Return every song row, as raw text.

        Args:
            source: Where the list is: a sheet URL, or a path to a local CSV file.

        Raises:
            SongListError: The list can't be read, or an expected column is missing.
        """


class MediaSource(ABC):
    """Looks up and downloads videos."""

    @abstractmethod
    def lookup(self, url: str) -> MediaInfo:
        """Return the video's ID, title and (rounded) length, without downloading it.

        Raises:
            MediaUnavailableError: The video doesn't exist or can't be accessed.
        """

    @abstractmethod
    def download(self, url: str, kind: MediaKind, dest_dir: Path, stem: str) -> Path:
        """Download one video into dest_dir, named <stem>.<extension>.

        Must be safe to call from several threads at once.

        Returns:
            The path of the downloaded file.

        Raises:
            DownloadError: The download failed. Its `retryable` flag says whether
                trying again might help.
        """


class MediaProcessor(ABC):
    """Measures media files and renders the final output."""

    @abstractmethod
    def measure(self, path: Path, start_s: float, end_s: float | None) -> ClipInfo:
        """Return the file's real length, and its peak level within [start_s, end_s].

        Args:
            end_s: None means "to the end of the file". A range reaching past the
                end of the file is measured up to the end.

        Raises:
            RenderError: The file can't be read.
        """

    @abstractmethod
    def render(self, plan: RenderPlan, output_path: Path) -> Path:
        """Render the plan into one file at output_path.

        Raises:
            MediaToolMissingError: The media tool isn't available.
            RenderError: Rendering failed.
        """

    @abstractmethod
    def describe(self) -> str:
        """Which tool is used and its version, for the log at run start."""


class EventSink(ABC):
    """Receives log events as they happen (the console now, the GUI later)."""

    @abstractmethod
    def emit(self, event: LogEvent) -> None:
        """Handle one event. Must be safe to call from several threads at once."""
