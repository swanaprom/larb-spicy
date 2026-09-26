"""
test_google_api.py

Quick-and-dirty access test for a Google Sheet that has "Anyone with the
link can edit" sharing enabled. Because the sheet is public, we don't need
OAuth / a service account / API key at all -- Google Sheets exposes a CSV
export endpoint that works for any publicly viewable/editable sheet:

    https://docs.google.com/spreadsheets/d/<SHEET_ID>/export?format=csv&gid=<GID>

This script:
1. Defines the sheet URL as a constant.
2. Converts it to the CSV export URL.
3. Downloads the CSV.
4. Parses it into a nested list: outer list = rows, inner list = columns.

Note: this ONLY works for sheets shared as "Anyone with the link" (viewer
or editor). Private sheets will return an HTML login page instead of CSV,
and this script will fail loudly rather than silently parse garbage.
"""

import csv
import io
import re
import sys

import requests

# ---------------------------------------------------------------------------
# Constant: paste the normal "shareable" Google Sheet URL here.
# Example: https://docs.google.com/spreadsheets/d/1AbCDEfGhIjKlMnOpQrStUvWxYz/edit#gid=0
# ---------------------------------------------------------------------------
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1zGVp4IefmFykJjLN_Yvz904h7J5J1HEkYuGUFB4Bj4A/edit?gid=0#gid=0"

# Optional: force a specific tab's gid instead of whatever gid (if any) is
# embedded in GOOGLE_SHEET_URL. Each tab in a spreadsheet has its own gid --
# find it by clicking the tab and reading the "#gid=..." part of the URL.
# Leave as None to just use whatever gid is in GOOGLE_SHEET_URL (or 0).
GID_OVERRIDE = None  # e.g. "123456789"


def _extract_sheet_id_and_gid(sheet_url: str, gid_override: str = None):
    """Pull the spreadsheet ID out of a normal share URL, and resolve the gid
    (tab) to use: explicit override > gid in the URL > default "0"."""
    id_match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url)
    if not id_match:
        raise ValueError(f"Could not find a spreadsheet ID in URL: {sheet_url}")
    sheet_id = id_match.group(1)

    if gid_override is not None:
        gid = str(gid_override)
    else:
        gid_match = re.search(r"[#&?]gid=(\d+)", sheet_url)
        gid = gid_match.group(1) if gid_match else "0"

    return sheet_id, gid


def build_csv_export_url(sheet_url: str, gid_override: str = None) -> str:
    sheet_id, gid = _extract_sheet_id_and_gid(sheet_url, gid_override)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def fetch_sheet_as_csv_text(sheet_url: str, gid_override: str = None) -> str:
    export_url = build_csv_export_url(sheet_url, gid_override)
    response = requests.get(export_url, timeout=15)

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch sheet (HTTP {response.status_code}). "
            "Check that the sheet is shared as 'Anyone with the link'."
        )

    content_type = response.headers.get("Content-Type", "")
    if "text/csv" not in content_type:
        # Google redirects to a login/HTML page for private sheets instead
        # of erroring, so we have to sanity-check the content type.
        raise RuntimeError(
            "Response was not CSV (got Content-Type: "
            f"{content_type!r}). The sheet is probably not public, or the "
            "gid/tab doesn't exist."
        )

    # requests doesn't reliably detect the encoding from headers alone, and
    # Google's CSV export is always UTF-8. Without this, Thai/CJK/etc. text
    # comes back mangled (mis-decoded as Latin-1/Windows-1252 gibberish).
    # Decoding the raw bytes ourselves sidesteps that guesswork entirely.
    return response.content.decode("utf-8")


def parse_csv_to_nested_list(csv_text: str) -> list:
    """Return a nested list: [ [row0_col0, row0_col1, ...], [row1_col0, ...], ... ]"""
    reader = csv.reader(io.StringIO(csv_text))
    return [row for row in reader]


def get_sheet_as_table(sheet_url: str = GOOGLE_SHEET_URL, gid_override: str = GID_OVERRIDE) -> list:
    """Convenience wrapper: URL (+ optional gid override) in, nested list out.
    Import this elsewhere, e.g.:
        get_sheet_as_table(GOOGLE_SHEET_URL, gid_override="123456789")
    """
    csv_text = fetch_sheet_as_csv_text(sheet_url, gid_override)
    return parse_csv_to_nested_list(csv_text)


def main():
    try:
        table = get_sheet_as_table(GOOGLE_SHEET_URL, GID_OVERRIDE)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Fetched {len(table)} rows.")
    for i, row in enumerate(table):
        print(f"{i}: {row}")


if __name__ == "__main__":
    main()