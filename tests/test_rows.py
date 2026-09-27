"""Row range (--rows): parsing, and checking it against the sheet."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import CD_MP3, XG, FakeMedia, PipelineTestCase, row  # noqa: E402
from larb.core.errors import LarbError  # noqa: E402
from larb.core.manifest import parse_row_range, select_rows  # noqa: E402
from larb.core.models import ProcessingSettings, RowRange, Settings  # noqa: E402

# Rows 2-4 and 6; row 5 is empty in the sheet, so the sheet adapter doesn't return it.
SHEET = [row(2, "fx://a", "0:01-0:02"), row(3, "fx://b", "0:01-0:02"),
         row(4, "fx://c", "0:01-0:02"), row(6, "fx://d", "0:01-0:02")]


class ParseRowRangeTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_row_range("2-3"), RowRange(2, 3))
        self.assertEqual(parse_row_range(" 2 – 10 "), RowRange(2, 10))   # spaces, en dash
        self.assertEqual(parse_row_range("5"), RowRange(5, 5))           # one row alone

    def test_backwards(self):
        with self.assertRaisesRegex(LarbError, "backwards"):
            parse_row_range("5-3")

    def test_header_row(self):
        with self.assertRaisesRegex(LarbError, "header"):
            parse_row_range("1-3")

    def test_not_a_range(self):
        for text in ("", "a-b", "2-", "2,3", "-3"):
            with self.assertRaises(LarbError, msg=text):
                parse_row_range(text)


class SelectRowsTest(unittest.TestCase):
    def test_inside(self):
        self.assertEqual([r.row_number for r in select_rows(SHEET, RowRange(3, 6))], [3, 4, 6])
        self.assertEqual([r.row_number for r in select_rows(SHEET, RowRange(2, 2))], [2])

    def test_outside_the_sheet(self):
        with self.assertRaisesRegex(LarbError, "outside the sheet: the last song is on row 6"):
            select_rows(SHEET, RowRange(5, 7))
        with self.assertRaisesRegex(LarbError, "outside the sheet"):
            select_rows([], RowRange(2, 2))


class RowRangePipelineTest(PipelineTestCase):
    def test_only_those_rows(self):
        media = FakeMedia({"fx://xg": (XG, 189.0)})
        rows = [row(2, "fx://xg", "0:10-0:20"), row(3, "fx://xg", "0:30-0:40"),
                row(4, "fx://missing", "0:10-0:20")]        # outside the range: never looked up
        result = self.run_pipeline(rows, media, CD_MP3, Settings(processing=ProcessingSettings()),
                                   row_range=RowRange(3, 3))
        self.assertEqual(result.songs_rendered, 1)
        self.assertEqual(result.row_errors, 0)
        self.assertEqual(media.lookups, 1)

    def test_outside_stops_before_any_lookup(self):
        media = FakeMedia({"fx://xg": (XG, 189.0)})
        with self.assertRaisesRegex(LarbError, "outside the sheet"):
            self.run_pipeline([row(2, "fx://xg", "0:10-0:20")], media, CD_MP3, Settings(),
                              row_range=RowRange(2, 9))
        self.assertEqual((media.lookups, media.downloads), (0, 0))


if __name__ == "__main__":
    unittest.main()
