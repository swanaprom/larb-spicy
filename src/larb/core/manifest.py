"""Turning raw sheet rows into validated songs (SPEC §8).

Pure rules, no tools: everything here can be tested without internet or FFmpeg.
"""

import re
from dataclasses import dataclass

from larb.core.errors import LarbError
from larb.core.models import RowRange, SheetRow

# One time: m:ss, m.ss, or h:mm:ss. Seconds (and minutes after hours) need two digits,
# so "1.5" is rejected instead of guessed as 1:05 or 1:50.
_TIME = r"(\d+)[.:](\d{2})(?:[.:](\d{2}))?"
# Dash between start and end: hyphen, or the en/em dashes phones like to insert.
_RANGE_RE = re.compile(rf"^{_TIME}[-–—]{_TIME}$")


class RowProblem(Exception):
    """A row can't be used. The message is shown to the operator as the reason."""


def _to_seconds(a: str, b: str, c: str | None) -> int:
    if c is None:  # m:ss
        minutes, seconds = int(a), int(b)
        if seconds >= 60:
            raise RowProblem(f"seconds must be under 60 (got {a}:{b})")
        return minutes * 60 + seconds
    hours, minutes, seconds = int(a), int(b), int(c)  # h:mm:ss
    if minutes >= 60 or seconds >= 60:
        raise RowProblem(f"minutes and seconds must be under 60 (got {a}:{b}:{c})")
    return hours * 3600 + minutes * 60 + seconds


def parse_time_range(text: str) -> tuple[int, int]:
    """Parse "0:27 - 1:04" into (27, 64) seconds.

    People type stray spaces inside numbers ("1. 04", "0.4 6-1:3 0"), so ALL
    whitespace is removed before parsing, not just at the ends. Don't "simplify"
    this to .strip() — the real sheet has these (TECH §4).

    Raises:
        RowProblem: The text isn't a range, or start isn't before end.
    """
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        raise RowProblem("time range is empty")
    match = _RANGE_RE.match(compact)
    if not match:
        raise RowProblem(f"time range {text!r} isn't in a form like 0:27-1:04")
    g = match.groups()
    start, end = _to_seconds(*g[0:3]), _to_seconds(*g[3:6])
    if start >= end:
        raise RowProblem(f"time range {text!r}: start must be before end")
    return start, end


def is_marked(text: str) -> bool:
    """The "already mirrored" column: empty or only spaces = no; anything else = yes (SPEC §8)."""
    return bool((text or "").strip())


@dataclass(frozen=True)
class ParsedRow:
    """A row that passed the offline checks, before asking the media source about it."""

    row_number: int
    title: str
    artist: str
    url: str
    start_s: int
    end_s: int
    already_mirrored: bool
    warnings: tuple[str, ...]


def parse_row(row_number: int, title: str, artist: str, url: str,
              time_range: str, mirrored: str) -> ParsedRow:
    """Apply the offline rules of SPEC §8 to one row.

    Raises:
        RowProblem: The row is a row error (missing URL, bad time range).
    """
    url = (url or "").strip()
    if not url:
        raise RowProblem("URL is empty")
    start, end = parse_time_range(time_range)
    warnings = []
    title, artist = (title or "").strip(), (artist or "").strip()
    if not title:
        warnings.append("song title is empty")
    if not artist:
        warnings.append("artist is empty")
    return ParsedRow(row_number, title, artist, url, start, end, is_marked(mirrored), tuple(warnings))


# --rows: "2-10", or one row alone ("5" = "5-5"). Any dash type, spaces allowed.
_ROWS_RE = re.compile(r"^(\d+)(?:[-–—](\d+))?$")
FIRST_SONG_ROW = 2   # row 1 is the header


def parse_row_range(text: str) -> RowRange:
    """Parse the operator's row range, e.g. "2-10" or "5".

    Only the form is checked here; whether the rows exist is checked against the
    sheet by select_rows().

    Raises:
        LarbError: Not a range, a backwards range, or it includes the header row.
    """
    match = _ROWS_RE.match(re.sub(r"\s+", "", text or ""))
    if not match:
        raise LarbError(f"Row range {text!r} isn't in a form like 2-10 (or 5 for one row)")
    first = int(match.group(1))
    last = int(match.group(2)) if match.group(2) else first
    if first > last:
        raise LarbError(f"Row range {text!r} is backwards: the first row must not be after the last")
    if first < FIRST_SONG_ROW:
        raise LarbError(f"Row range {text!r} starts before row {FIRST_SONG_ROW}: row 1 is the "
                        f"header, so songs start at row {FIRST_SONG_ROW}")
    return RowRange(first, last)


def select_rows(rows: list[SheetRow], wanted: RowRange) -> list[SheetRow]:
    """Keep only the rows inside the range (row numbers as shown in the sheet).

    Raises:
        LarbError: The range reaches past the sheet's last song row.
    """
    last_row = max((r.row_number for r in rows), default=FIRST_SONG_ROW - 1)
    if wanted.last > last_row:
        where = f"the last song is on row {last_row}" if rows else "the sheet has no songs"
        raise LarbError(f"Row range {wanted.first}-{wanted.last} is outside the sheet: {where}")
    return [r for r in rows if wanted.first <= r.row_number <= wanted.last]
