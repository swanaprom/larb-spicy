"""Data types the core works with. Plain data only, no behavior that needs a tool."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


# ---------------------------------------------------------------------------
# Settings (mirrors the TOML schema in SPEC §7, minus [sheet.columns], which
# only the sheet adapter knows about)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OutputSettings:
    directory: str = ""
    filename_template: str = ""  # without extension; "" means "{date}_{time}"


@dataclass(frozen=True)
class CountdownSettings:
    default_urls: tuple[str, ...] = ()
    default_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class DownloadSettings:
    cache_directory: str = ""
    max_parallel_downloads: int = 3
    max_retries: int = 2
    max_height: int = 720


@dataclass(frozen=True)
class ProcessingSettings:
    audio_only: bool = True
    mirror: bool = False
    crossfade_duration_seconds: float = 1.0


@dataclass(frozen=True)
class Settings:
    """All settings for one run. Frozen: settings are locked for the whole run (SPEC §5)."""

    output: OutputSettings = field(default_factory=OutputSettings)
    countdown: CountdownSettings = field(default_factory=CountdownSettings)
    download: DownloadSettings = field(default_factory=DownloadSettings)
    processing: ProcessingSettings = field(default_factory=ProcessingSettings)


# ---------------------------------------------------------------------------
# Song list
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SheetRow:
    """One row of the song list, as raw text. The core parses and validates it (SPEC §8).

    Attributes:
        row_number: The row's number as the operator sees it in the sheet
            (the header is row 1, so the first song is row 2).
    """

    row_number: int
    song_title: str
    artist: str
    url: str
    time_range: str
    mirrored: str


@dataclass(frozen=True)
class MediaInfo:
    """What the media source knows about a video before downloading it.

    Attributes:
        media_id: A stable ID for the video (YouTube: the 11-character video ID).
        duration_s: Length as reported by the source. YouTube rounds it to whole
            seconds, so the real file is checked again after download.
    """

    media_id: str
    title: str
    duration_s: float


@dataclass(frozen=True)
class MediaKind:
    """What to download: audio only, or video up to a maximum height."""

    audio_only: bool
    max_height: int

    @property
    def cache_suffix(self) -> str:
        """Part of the cache file name: "audio" or e.g. "v720" (see HANDOFF.md)."""
        return "audio" if self.audio_only else f"v{self.max_height}"


# ---------------------------------------------------------------------------
# Media processing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClipInfo:
    """Measured facts about a media file.

    Attributes:
        duration_s: The real length of the whole file.
        peak_db: The loudest sample within the measured range, in dBFS (0 = full scale).
    """

    duration_s: float
    peak_db: float


@dataclass(frozen=True)
class Segment:
    """One piece of the final output: a countdown or a trimmed song."""

    path: Path
    start_s: float
    end_s: float
    mirror: bool
    gain_db: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class RenderPlan:
    """Everything the renderer needs. Segments play in order, crossfaded at every join."""

    segments: tuple[Segment, ...]
    crossfade_s: float
    audio_only: bool
    height: int

    @property
    def expected_duration_s(self) -> float:
        """Output length: all segments, minus one crossfade per join (TECH §10)."""
        joins = max(len(self.segments) - 1, 0)
        return sum(s.duration_s for s in self.segments) - self.crossfade_s * joins


# ---------------------------------------------------------------------------
# Events (log stream to console now, GUI later)
# ---------------------------------------------------------------------------

class Level(Enum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40


@dataclass(frozen=True)
class LogEvent:
    level: Level
    stage: str
    message: str
    row_number: int | None = None


# ---------------------------------------------------------------------------
# Pipeline results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ManifestEntry:
    """A validated song, ready to download and render."""

    row_number: int
    title: str
    artist: str
    url: str
    start_s: float
    end_s: float
    already_mirrored: bool
    media: MediaInfo

    @property
    def display_name(self) -> str:
        """Name for logs: title (and artist) if the sheet has them, else the URL."""
        if self.title and self.artist:
            return f"{self.title} - {self.artist}"
        return self.title or self.media.title or self.url


@dataclass
class RunResult:
    output_path: Path
    songs_rendered: int
    row_errors: int
    row_warnings: int
