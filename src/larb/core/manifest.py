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


# Short reasons a row can't be used, the same for every row with that kind of problem.
# Est. Length counts left-out rows by these (GUI.md 3.2).
URL_EMPTY = "URL is empty"
BAD_TIME_RANGE = "time range can't be read"
START_PAST_END = "start is past the end of the song"
END_PAST_END = "end is more than 1 s past the end of the song"
CLIP_TOO_SHORT = "clip is too short"
CACHED_UNREADABLE = "cached file can't be read"


class RowProblem(Exception):
    """A row can't be used. The message is shown to the operator as the reason.

    Attributes:
        reason: One of the short reasons above, for counting rows by kind of problem.
            "" = no general reason given; the message is the reason.
    """

    def __init__(self, message: str, reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason


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
        raise RowProblem("URL is empty", URL_EMPTY)
    try:
        start, end = parse_time_range(time_range)
    except RowProblem as problem:
        raise RowProblem(str(problem), BAD_TIME_RANGE) from None
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


def _checked_range(first: int | None, last: int | None, shown: str) -> RowRange:
    """The form checks shared by the command line and the GUI's two fields."""
    if first is not None and last is not None and first > last:
        raise LarbError(f"Row range {shown} is backwards: the first row must not be after the last")
    for edge in (first, last):
        if edge is not None and edge < FIRST_SONG_ROW:
            raise LarbError(f"Row range {shown} includes row {edge}: row 1 is the header, "
                            f"so songs start at row {FIRST_SONG_ROW}")
    return RowRange(first, last)


def parse_row_range(text: str) -> RowRange:
    """Parse the operator's row range, e.g. "2-10" or "5" (the command line's --rows).

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
    return _checked_range(first, last, repr(text))


def row_range_from_fields(first_text: str, last_text: str) -> RowRange | None:
    """The GUI's "from" and "to" fields as a row range. An empty field is an open
    edge (SPEC §8): from 3 and an empty "to" = row 3 to the last row.

    Returns:
        None when both fields are empty (all rows).

    Raises:
        LarbError: A field isn't a whole number, the range is backwards, or it
            includes the header row.
    """
    edges = []
    for name, text in (("from", first_text), ("to", last_text)):
        text = re.sub(r"\s+", "", text or "")
        if text and not text.isdecimal():
            raise LarbError(f"Rows {name} {text!r} isn't a row number")
        edges.append(int(text) if text else None)
    if edges == [None, None]:
        return None
    first, last = edges
    return _checked_range(first, last, f"{first or '(first)'}-{last or '(last)'}")


def select_rows(rows: list[SheetRow], wanted: RowRange) -> list[SheetRow]:
    """Keep only the rows inside the range (row numbers as shown in the sheet).
    An open edge (None) reaches the first or last song row.

    Raises:
        LarbError: The range reaches past the sheet's last song row.
    """
    last_row = max((r.row_number for r in rows), default=FIRST_SONG_ROW - 1)
    first = wanted.first if wanted.first is not None else FIRST_SONG_ROW
    last = wanted.last if wanted.last is not None else last_row
    if max(first, last) > last_row:
        where = f"the last song is on row {last_row}" if rows else "the sheet has no songs"
        raise LarbError(f"Row range {wanted.describe()} is outside the sheet: {where}")
    return [r for r in rows if first <= r.row_number <= last]
