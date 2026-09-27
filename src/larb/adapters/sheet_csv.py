"""SongListSource for a public Google Sheet (CSV export) or a local CSV file.

Only this adapter knows the sheet's column names (from [sheet.columns]); the
core sees SheetRow fields, never column names.
"""

import csv
import io
import re
import urllib.error
import urllib.request
from pathlib import Path

from larb.core.errors import SongListError
from larb.core.models import SheetRow
from larb.core.ports import SongListSource

FIELDS = ("song_title", "artist", "url", "time_range", "mirrored")
TIMEOUT_S = 30


def _export_url(sheet_url: str) -> str:
    """Turn a normal share link into its CSV export link (same tab: gid in the URL, else 0)."""
    id_match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", sheet_url)
    if not id_match:
        raise SongListError(f"Can't find a spreadsheet ID in {sheet_url}")
    gid_match = re.search(r"[#&?]gid=(\d+)", sheet_url)
    gid = gid_match.group(1) if gid_match else "0"
    return f"https://docs.google.com/spreadsheets/d/{id_match.group(1)}/export?format=csv&gid={gid}"


class CsvSongListSource(SongListSource):
    """Args:
        columns: Field name -> column header, from [sheet.columns] in the settings file.
    """

    def __init__(self, columns: dict[str, str]) -> None:
        missing = [f for f in FIELDS if not columns.get(f)]
        if missing:
            raise SongListError(f"[sheet.columns] is missing: {', '.join(missing)}")
        self._columns = columns

    def fetch_rows(self, source: str) -> list[SheetRow]:
        if source.startswith(("http://", "https://")):
            text = self._download(source)
        else:
            try:
                # utf-8-sig: a CSV saved by Excel/Notepad may start with a BOM.
                text = Path(source).read_text(encoding="utf-8-sig")
            except OSError as e:
                raise SongListError(f"Can't read {source}: {e}") from None
        return self._parse(text)

    def _download(self, sheet_url: str) -> str:
        url = _export_url(sheet_url)
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:
                content_type = response.headers.get("Content-Type", "")
                raw = response.read()
        except urllib.error.HTTPError as e:
            raise SongListError(f"The sheet can't be read (HTTP {e.code}). Is it shared as "
                                "'Anyone with the link'?") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise SongListError(f"The sheet can't be reached: {e}") from None
        # A sheet that isn't public returns a sign-in HTML page with a success
        # status, not an error (TECH §4), so check what actually came back.
        # Google's CSV export is always UTF-8. Decode the raw bytes ourselves:
        # guessing the encoding garbles Thai text (fix carried over from the prototype).
        text = raw.decode("utf-8-sig", errors="replace")
        if "text/csv" not in content_type or text.lstrip().startswith("<"):
            raise SongListError("The sheet isn't publicly viewable: share it as 'Anyone with the "
                                "link can view' (or the tab/gid doesn't exist).")
        return text

    def _parse(self, text: str) -> list[SheetRow]:
        table = list(csv.reader(io.StringIO(text)))
        if not table:
            raise SongListError("The song list is empty")
        header = [h.strip() for h in table[0]]
        index = {}
        for field in FIELDS:
            name = self._columns[field].strip()
            if name not in header:
                raise SongListError(f"Column {name!r} (for {field}) isn't in the sheet's header row. "
                                    f"Found: {', '.join(repr(h) for h in header if h)}")
            index[field] = header.index(name)
        rows = []
        for number, cells in enumerate(table[1:], start=2):   # row 1 is the header
            if not any(c.strip() for c in cells):
                continue  # fully empty rows are just spacing
            get = lambda f: cells[index[f]] if index[f] < len(cells) else ""
            rows.append(SheetRow(number, get("song_title"), get("artist"), get("url"),
                                 get("time_range"), get("mirrored")))
        return rows
