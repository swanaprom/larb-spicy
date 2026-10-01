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
    max_parallel_lookups: int = 5


DEFAULT_CROSSFADE_S = 0.8   # also in config/example.toml (SPEC §7)


@dataclass(frozen=True)
class ProcessingSettings:
    audio_only: bool = True
    mirror: bool = False
    crossfade_duration_seconds: float = DEFAULT_CROSSFADE_S


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
class RowRange:
    """Which sheet rows to use, both ends included, numbered as the operator sees
    them in the sheet (the header is row 1, so the first song is row 2).

    Attributes:
        first: None = an open edge: from the first song row (SPEC §8).
        last: None = an open edge: to the last row with content.
    """

    first: int | None
    last: int | None

    def describe(self) -> str:
        """For the log, e.g. "2-10", "3-(last)", "(first)-10"."""
        return f"{self.first or '(first)'}-{self.last or '(last)'}"


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
        audio_s: Seconds of audio that actually decode within the measured range.
            None = not known.
        video_s: Seconds of video within the measured range. None = no video, or
            not known. The renderer pads a short stream (silence, or the last
            frame repeated); the core warns when that would hide a real gap.
        has_video: Whether the file has a picture. A cover image (e.g. in an MP3)
            doesn't count: such a clip is shown as a black screen in video mode.
    """

    duration_s: float
    peak_db: float
    audio_s: float | None = None
    video_s: float | None = None
    has_video: bool = True


@dataclass(frozen=True)
class Segment:
    """One piece of the final output: a countdown or a trimmed song.

    Attributes:
        has_video: False = the file has no picture; in video mode the renderer shows a
            black screen for the segment's length (the core decides and warns).
    """

    path: Path
    start_s: float
    end_s: float
    mirror: bool
    gain_db: float
    has_video: bool = True

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class RenderPlan:
    """Everything the renderer needs. Segments play in order, crossfaded at every join.

    Attributes:
        crossfades_s: The crossfade length of each join, in order: one fewer than
            segments. Usually all the setting's value; the core shortens a join
            whose clips are too short to hold it (pipeline.plan_crossfades).
        fade_out_s: The output fades to silence (and to black) over its last
            fade_out_s seconds, ending exactly at the end. 0 = no fade. The core
            decides it; the renderer only applies it. It doesn't change the length.
    """

    segments: tuple[Segment, ...]
    crossfades_s: tuple[float, ...]
    audio_only: bool
    height: int
    fade_out_s: float = 0.0

    def __post_init__(self) -> None:
        if len(self.crossfades_s) != max(len(self.segments) - 1, 0):
            raise ValueError(f"{len(self.segments)} segments need {len(self.segments) - 1} "
                             f"crossfades, got {len(self.crossfades_s)}")

    @property
    def expected_duration_s(self) -> float:
        """Output length: all segments, minus each join's crossfade (TECH §10)."""
        return sum(s.duration_s for s in self.segments) - sum(self.crossfades_s)


# ---------------------------------------------------------------------------
# Events (log stream to console now, GUI later)
# ---------------------------------------------------------------------------

class Level(Enum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40


@dataclass(frozen=True)
class Activity:
    """Something that runs for a while alongside others, e.g. one download.

    The GUI shows one line per started activity until it ends, with a timer.

    Attributes:
        key: Stable ID, the same in the started and ended events (e.g. the cache
            stem "abc123_v720"; two songs can share a title, never a key).
        label: What to show, e.g. "Perfect Night - LE SSERAFIM".
        started: True when it starts; False when it ends (done, failed or stopped).
    """

    key: str
    label: str
    started: bool


@dataclass(frozen=True)
class LogEvent:
    """One thing that happened, for the console, the log file and the GUI.

    Attributes:
        progress: (done, total) when the event reports progress through a stage,
            e.g. (12, 40) for "checked 12 of 40 rows". The GUI reads this field,
            never the message text. None for ordinary events.
        activity: Set when the event marks an activity starting or ending (e.g. a
            download). Such events are DEBUG, so they don't clutter the console or
            the GUI's log. The GUI reads this field, never the message text.
    """

    level: Level
    stage: str
    message: str
    row_number: int | None = None
    progress: tuple[int, int] | None = None
    activity: Activity | None = None


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


@dataclass(frozen=True)
class LengthEstimate:
    """Est. Length's answer (GUI.md 3.2): the output's planned length, worked out
    without downloading songs.

    Attributes:
        length_s: The planned output length. 0 when no song is usable.
        songs: How many songs it counts.
        from_cache: Of those, how many were measured from their cached file (exact);
            the others count by their time range, padding included.
        left_out: (reason, number of rows) for rows a run would skip, in the order
            each reason first appears in the sheet.
    """

    length_s: float
    songs: int
    from_cache: int
    left_out: tuple[tuple[str, int], ...] = ()


@dataclass
class RunResult:
    output_path: Path
    songs_rendered: int
    row_errors: int
    row_warnings: int
    cache_dir: Path     # where this run's downloads are kept (for the clear-cache question)
