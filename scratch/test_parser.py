"""
test_parser.py

Pulls the raw table from test_google_api.py and cleans it up into a
manifest-ready nested list:

1. Drops the first row (header/titles).
2. Column index 2 (3rd column, "URLs"): normalizes any
   YouTube URL variant (youtu.be, watch?v=, with tracking/trailing junk)
   into the canonical "https://www.youtube.com/watch?v=<ID>" form.
   Rows with an unparsable link are dropped, with a warning.
3. Column index 3 (4th column, "ช่วงเวลา"): parses a timestamp range like
   "0.48 - 1.13", "0:48-1:13", "0.48 - 1:13", etc. into total seconds,
   and EXPANDS it into two columns: [start_seconds, end_seconds],
   pushing whatever was in the old 5th column (and beyond) one slot to
   the right instead of overwriting it. Rows with an unparsable
   timestamp are dropped, with a warning.

Column indexing recap (0-based) BEFORE this script touches anything:
    0: col 1
    1: col 2
    2: col 3  <- YouTube URL
    3: col 4  <- timestamp range ("start - end")
    4: col 5  <- whatever else was already there
    ...

AFTER processing:
    0: col 1
    1: col 2
    2: col 3  <- normalized YouTube URL
    3: col 4  <- start time, in seconds
    4: col 5  <- end time, in seconds
    5: col 6  <- (old col 5, shifted right)
    ...
"""

import re
import sys

from test_google_api import GOOGLE_SHEET_URL, GID_OVERRIDE, get_sheet_as_table

# 2026-09 sheet layout: ชื่อเพลง, ศิลปิน, URLs, ช่วงเวลา, ผู้เสนอเพลง + ชั้นปี, Mirrored แล้ว, หมายเหตุ
YOUTUBE_COLUMN_INDEX = 2   # 3rd column ("URLs")
TIMESTAMP_COLUMN_INDEX = 3  # 4th column ("ช่วงเวลา")

# Matches an 11-char YouTube video ID after v=, youtu.be/, embed/, or shorts/,
# regardless of what junk (tracking params, playlist refs, trailing slashes,
# extra path segments) surrounds it.
_YOUTUBE_ID_RE = re.compile(
    r"(?:youtu\.be/|(?:v|shorts|embed)/|[?&]v=)([A-Za-z0-9_-]{11})"
)

# Matches "M.S - M.S", "M:S-M:S", "M.S- M:S", etc:
#   - minute/second separator is '.' or ':'
#   - the range dash may or may not have surrounding spaces
_TIMESTAMP_RANGE_RE = re.compile(
    r"^\s*(\d+)[.:](\d+)\s*-\s*(\d+)[.:](\d+)\s*$"
)


def normalize_youtube_url(raw_url: str) -> str:
    """Return canonical https://www.youtube.com/watch?v=<ID>, or None if
    no valid 11-character video ID could be found in raw_url."""
    if not raw_url:
        return None

    match = _YOUTUBE_ID_RE.search(raw_url.strip())
    if not match:
        return None

    video_id = match.group(1)
    return f"https://www.youtube.com/watch?v={video_id}"


def _mmss_to_seconds(minutes: str, seconds: str) -> int:
    return int(minutes) * 60 + int(seconds)


def parse_timestamp_range(raw_range: str):
    """Parse a '<start> - <end>' timestamp string into (start_sec, end_sec).
    Returns None if the string doesn't match the expected shape."""
    if not raw_range:
        return None

    # People type stray spaces inside numbers ("1. 04", "0.4 6-1:3 0"), so
    # drop ALL whitespace before matching, not just the ends.
    match = _TIMESTAMP_RANGE_RE.match(re.sub(r"\s+", "", raw_range))
    if not match:
        return None

    start_min, start_sec, end_min, end_sec = match.groups()
    start_total = _mmss_to_seconds(start_min, start_sec)
    end_total = _mmss_to_seconds(end_min, end_sec)
    return start_total, end_total


def build_manifest(raw_table: list) -> list:
    """Apply all three transformations and return the cleaned nested list."""
    if not raw_table:
        return []

    rows = raw_table[1:]  # 1. drop header row
    manifest = []

    for row_number, row in enumerate(rows, start=2):  # start=2: matches sheet row #, since row 1 was the header
        row = list(row)  # avoid mutating the caller's data

        # --- guard against short/malformed rows ---
        if len(row) <= max(YOUTUBE_COLUMN_INDEX, TIMESTAMP_COLUMN_INDEX):
            print(
                f"[WARNING] Row {row_number}: not enough columns "
                f"({len(row)} found) to contain a YouTube URL and "
                "timestamp. Dropping row.",
                file=sys.stderr,
            )
            continue

        # --- 2. normalize YouTube URL ---
        raw_url = row[YOUTUBE_COLUMN_INDEX]
        clean_url = normalize_youtube_url(raw_url)
        if clean_url is None:
            print(
                f"[WARNING] Row {row_number}: could not parse a valid "
                f"YouTube URL from {raw_url!r}. Dropping row.",
                file=sys.stderr,
            )
            continue
        row[YOUTUBE_COLUMN_INDEX] = clean_url

        # --- 3. normalize timestamp range into two columns ---
        raw_range = row[TIMESTAMP_COLUMN_INDEX]
        parsed_range = parse_timestamp_range(raw_range)
        if parsed_range is None:
            print(
                f"[WARNING] Row {row_number}: could not parse timestamp "
                f"range from {raw_range!r}. Dropping row.",
                file=sys.stderr,
            )
            continue
        start_sec, end_sec = parsed_range
        # Replace the single timestamp-range column with two columns,
        # shifting everything after it (old col 6+) one slot to the right.
        row[TIMESTAMP_COLUMN_INDEX:TIMESTAMP_COLUMN_INDEX + 1] = [start_sec, end_sec]

        manifest.append(row)

    return manifest


def get_manifest(sheet_url: str = GOOGLE_SHEET_URL, gid_override: str = GID_OVERRIDE) -> list:
    """Convenience wrapper for other modules: fetch + clean in one call."""
    raw_table = get_sheet_as_table(sheet_url, gid_override)
    return build_manifest(raw_table)


def main():
    try:
        manifest = get_manifest(GOOGLE_SHEET_URL, GID_OVERRIDE)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Manifest built with {len(manifest)} valid row(s).")
    for i, row in enumerate(manifest):
        print(f"{i}: {row}")


if __name__ == "__main__":
    main()