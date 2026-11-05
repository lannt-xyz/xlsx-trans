import datetime
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import fixtures as fx
from tests.fixtures import FakeTranslator, default_cfg, run_process
from xlsx_trans import markdown

try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None


class TestHelpers(unittest.TestCase):
    def test_md_fmt(self):
        cases = [
            (None, ""), (True, "TRUE"), (False, "FALSE"), (3.0, "3"), (3.5, "3.5"), (7, "7"), ("abc", "abc"),
            (datetime.datetime(2026, 11, 5), "2026-11-05"),
            (datetime.datetime(2026, 11, 5, 10, 30), "2026-11-05 10:30:00"),
            (datetime.date(2026, 11, 5), "2026-11-05"),
            (datetime.time(10, 30), "10:30:00"),
        ]
        for value, expected in cases:
            self.assertEqual(markdown.md_fmt(value), expected, repr(value))

    def test_md_cell_escapes_pipes_and_newlines(self):
        self.assertEqual(markdown.md_cell(" a|b\nc "), "a\\|b<br>c")
        self.assertEqual(markdown.md_cell("x\r\ny\rz"), "x<br>y<br>z")
        self.assertEqual(markdown.md_cell(None), "")

    def test_resolve(self):
        self.assertEqual(markdown.resolve_path("xl", "worksheets/sheet1.xml"), "xl/worksheets/sheet1.xml")
        self.assertEqual(markdown.resolve_path("xl/worksheets", "../drawings/d.xml"), "xl/drawings/d.xml")
        self.assertEqual(markdown.resolve_path("xl", "/xl/a.xml"), "xl/a.xml")


@unittest.skipUnless(openpyxl, "cần openpyxl")
class MarkdownTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.src = fx.build_fixture(self.dir / "in.xlsx")
        self.out = self.dir / "out.xlsx"
        self.md_path = self.out.with_suffix(".md")

    def translate(self, **cfg_kw):
        cfg = default_cfg(md=True, **cfg_kw)
        return run_process(self.src, self.out, cfg)

    def md(self, **cfg_kw):
        self.translate(**cfg_kw)
        return self.md_path.read_text(encoding="utf-8")


class TestMarkdownContent(MarkdownTestCase):
    def test_file_is_created_next_to_output(self):
        _, logs, _ = self.translate()
        self.assertTrue(self.md_path.exists())
        self.assertTrue(any("Đã xuất Markdown" in l for l in logs))

    def test_rows_use_excel_row_numbers_and_columns_use_letters(self):
        md = self.md()
        self.assertIn("| # | A | B | C | D |", md)
        self.assertIn("|---:|---|---|---|---|", md)
        self.assertIn("| 1 | EN[名前] | EN[数量] | EN[備考] |  |", md)
        self.assertIn("| 2 | EN[りんご] | 3 | EN[新鮮です] |  |", md)
        # ô công thức: lấy kết quả Excel đã tính sẵn (có thể vẫn là tiếng Nhật)
        self.assertIn("| 3 | EN[みかん] | 5 | ABC-123 | りんごx |", md)
        self.assertRegex(md, r"(?m)^\| 5 \| ")
        self.assertNotRegex(md, r"(?m)^\| 4 \| ")  # dòng trống bị bỏ nhưng số dòng giữ nguyên

    def test_second_sheet_table(self):
        md = self.md()
        self.assertIn("| # | A | B | C |\n|---:|---|---|---|\n| 3 |  | EN[合計] | 8 |", md)

    def test_pipes_and_newlines_are_escaped(self):
        md = self.md()
        self.assertIn("EN[1行目<br>2行目]", md)
        self.assertIn("EN[良い\\|悪い]", md)

    def test_sheet_names_are_original_with_translation_only_as_gloss(self):
        md = self.md()
        self.assertIn("## Danh sách sheet", md)
        self.assertIn("- 1. `売上` — EN[売上] — vùng dữ liệu `A1:D5`", md)
        self.assertIn("- 2. `Summary` — vùng dữ liệu `A1:C3`", md)
        self.assertIn("## Sheet 1: `売上` — EN[売上]", md)
        self.assertRegex(md, r"(?m)^## Sheet 2: `Summary`$")  # tên tiếng Anh: không có gloss
        self.assertIn("Tên sheet trong Excel: `売上`", md)

    def test_comments_and_text_boxes_are_listed_with_references(self):
        md = self.md()
        self.assertIn("**Comments**", md)
        self.assertIn("- `A2`: EN[確認してください]", md)
        self.assertIn("**Text box / shape**", md)
        self.assertIn("- gần `E6`: EN[注意事項です] / OK 123", md)
        self.assertEqual(md.count("注意事項です"), 1)  # mc:Fallback không bị liệt kê trùng

    def test_gloss_failure_still_produces_markdown_without_gloss(self):
        cfg = default_cfg(md=True)
        run_process(self.src, self.out, cfg, FakeTranslator(fail_on={"売上"}))
        md = self.md_path.read_text(encoding="utf-8")
        self.assertRegex(md, r"(?m)^## Sheet 1: `売上`$")

    def test_gloss_reuses_cached_translation(self):
        cfg = default_cfg(md=True)
        _, _, fake1 = run_process(self.src, self.out, cfg)
        self.assertEqual(len(fake1.calls), fx.UNIQUE_COUNT + 1)  # +1: tên sheet 売上
        _, _, fake2 = run_process(self.src, self.out, cfg)
        self.assertEqual(fake2.calls, [])  # cả bản dịch tên sheet cũng nằm trong cache

    def test_markdown_disabled(self):
        cfg = default_cfg(md=False)
        _, _, fake = run_process(self.src, self.out, cfg)
        self.assertFalse(self.md_path.exists())
        self.assertNotIn("売上", fake.calls)

    def test_export_failure_does_not_fail_the_translation(self):
        cfg = default_cfg(md=True)
        with mock.patch.object(markdown, "export_markdown", side_effect=RuntimeError("hỏng")):
            (applied, errors), logs, _ = run_process(self.src, self.out, cfg)
        self.assertEqual((applied, errors), (fx.UNIT_COUNT, 0))
        self.assertTrue(self.out.exists())
        self.assertTrue(any("Không xuất được Markdown" in l and "hỏng" in l for l in logs), logs)


class TestMarkdownLimits(MarkdownTestCase):
    def test_max_rows_truncates_with_note(self):
        md = self.md(md_max_rows=2)
        sheet1 = md.split("## Sheet 2:")[0]
        self.assertRegex(sheet1, r"(?m)^\| 1 \| ")
        self.assertRegex(sheet1, r"(?m)^\| 2 \| ")
        self.assertNotRegex(sheet1, r"(?m)^\| 3 \| ")
        self.assertNotRegex(sheet1, r"(?m)^\| 5 \| ")
        self.assertIn("đã cắt ở dòng 2", sheet1)

    def test_max_cols_limits_columns(self):
        md = self.md(md_max_cols=2)
        self.assertIn("| # | A | B |\n", md)
        self.assertNotIn("| D |", md)
        self.assertNotIn("りんごx", md)

    def test_direct_export_with_custom_gloss_and_limits(self):
        run_process(self.src, self.out, default_cfg())
        target = self.dir / "direct.md"
        logs = []
        path = markdown.export_markdown(self.out, target, gloss=lambda n: "G!" if n == "Summary" else None,
                                   log=logs.append, max_rows=100, max_cols=50)
        self.assertEqual(Path(path), target)
        md = target.read_text(encoding="utf-8")
        self.assertIn("## Sheet 2: `Summary` — G!", md)
        self.assertRegex(md, r"(?m)^## Sheet 1: `売上`$")
        self.assertEqual(logs, [])


if __name__ == "__main__":
    unittest.main()
