"""Row range (--rows, and the GUI's from/to fields): parsing, open edges, and checking
it against the sheet."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import CD_MP3, XG, FakeMedia, PipelineTestCase, row  # noqa: E402
from larb.core.errors import LarbError  # noqa: E402
from larb.core.manifest import parse_row_range, row_range_from_fields, select_rows  # noqa: E402
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


class OpenEdgeTest(unittest.TestCase):
    """SPEC §8: in the GUI, an empty "from" or "to" is an open edge."""

    def numbers(self, wanted):
        return [r.row_number for r in select_rows(SHEET, wanted)]

    def test_fields(self):
        self.assertIsNone(row_range_from_fields("", "  "))                 # both empty: all rows
        self.assertEqual(row_range_from_fields("3", ""), RowRange(3, None))
        self.assertEqual(row_range_from_fields("", "10"), RowRange(None, 10))
        self.assertEqual(row_range_from_fields(" 2 ", "1 0"), RowRange(2, 10))  # stray spaces

    def test_bad_fields(self):
        for first, last, reason in (("a", "", "isn't a row number"), ("", "3.5", "isn't a row number"),
                                    ("-2", "", "isn't a row number"), ("5", "3", "backwards"),
                                    ("1", "", "header"), ("", "1", "header")):
            with self.assertRaisesRegex(LarbError, reason, msg=(first, last)):
                row_range_from_fields(first, last)

    def test_select_open_edges(self):
        self.assertEqual(self.numbers(RowRange(3, None)), [3, 4, 6])     # row 3 to the last row
        self.assertEqual(self.numbers(RowRange(None, 3)), [2, 3])        # first song row to row 3
        self.assertEqual(self.numbers(RowRange(None, None)), [2, 3, 4, 6])
        self.assertEqual(self.numbers(RowRange(6, None)), [6])

    def test_open_edge_outside_the_sheet(self):
        with self.assertRaisesRegex(LarbError, r"7-\(last\) is outside the sheet: the last song is on row 6"):
            select_rows(SHEET, RowRange(7, None))
        with self.assertRaisesRegex(LarbError, "outside the sheet"):
            select_rows(SHEET, RowRange(None, 9))

    def test_command_line_unchanged(self):
        self.assertEqual(parse_row_range("3-4"), RowRange(3, 4))    # --rows keeps first-last


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

    def test_open_last_edge(self):
        media = FakeMedia({"fx://xg": (XG, 189.0)})
        rows = [row(2, "fx://missing", "0:10-0:20"),         # before the range: never looked up
                row(3, "fx://xg", "0:10-0:20"), row(4, "fx://xg", "0:30-0:40")]
        result = self.run_pipeline(rows, media, CD_MP3, Settings(processing=ProcessingSettings()),
                                   row_range=RowRange(3, None))
        self.assertEqual((result.songs_rendered, result.row_errors, media.lookups), (2, 0, 2))


if __name__ == "__main__":
    unittest.main()
