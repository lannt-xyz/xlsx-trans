"""Đồng bộ Excel Table sau khi dịch: ô tiêu đề và công thức tham chiếu tên cột."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests import fixtures as fx
from tests.fixtures import FakeTranslator, default_cfg, read_zip, run_process
from xlsx_trans import tables as tb
from xlsx_trans.xlsx_xml import NSMAP, parse

MAIN = fx.MAIN


class TestHelpers(unittest.TestCase):
    def test_column_letters_roundtrip(self):
        for i in (0, 1, 25, 26, 27, 51, 52, 701, 702, 16383):
            self.assertEqual(tb.col_index(tb.col_letters(i)), i)
        self.assertEqual(tb.col_letters(0), "A")
        self.assertEqual(tb.col_letters(26), "AA")

    def test_split_ref(self):
        self.assertEqual(tb.split_ref("C5"), (2, 5))
        self.assertEqual(tb.split_ref("$B$12"), (1, 12))

    def test_formula_name_escapes_special_characters(self):
        self.assertEqual(tb.formula_name("Qty"), "Qty")
        self.assertEqual(tb.formula_name("A[1]#'x"), "A'[1']'#''x")


def build(path, sheet_xml, table_names, sst, extra=None):
    cols = "".join(f'<tableColumn id="{i}" name="{n}"/>' for i, n in enumerate(table_names, 1))
    parts = {
        "[Content_Types].xml": fx._p(f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'),
        "xl/workbook.xml": fx._p(
            f'<workbook xmlns="{MAIN}"><sheets><sheet name="S" sheetId="1"/></sheets>'
            f'<definedNames><definedName name="Rng">T1[名前]</definedName></definedNames></workbook>'
        ),
        "xl/worksheets/sheet1.xml": fx._p(sheet_xml),
        "xl/worksheets/_rels/sheet1.xml.rels": fx._p(
            f'<Relationships xmlns="{fx.PKG_REL}"><Relationship Id="rId1" '
            f'Type="{fx.REL}/table" Target="../tables/table1.xml"/></Relationships>'
        ),
        "xl/tables/table1.xml": fx._p(
            f'<table xmlns="{MAIN}" id="1" name="T1" displayName="T1" ref="A1:B3">'
            f'<tableColumns count="{len(table_names)}">{cols}</tableColumns></table>'
        ),
        "xl/sharedStrings.xml": fx._p(
            f'<sst xmlns="{MAIN}">' + "".join(f"<si><t>{s}</t></si>" for s in sst) + "</sst>"
        ),
    }
    parts.update(extra or {})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in parts.items():
            z.writestr(k, v)
    return path


SHEET = (
    f'<worksheet xmlns="{MAIN}"><sheetData>'
    '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
    '<row r="2"><c r="A2"><v>1</v></c><c r="B2"><f>T1[[#This Row],[名前]]*2</f><v>2</v></c></row>'
    '<row r="3"><c r="A3"><v>2</v></c><c r="B3"><f>SUM(T1[数量])+T1[@名前]</f><v>3</v></c></row>'
    "</sheetData></worksheet>"
)


class Mapped(FakeTranslator):
    def __init__(self, mapping):
        super().__init__()
        self.mapping = mapping

    def __call__(self, text, cfg):
        self.calls.append(text)
        return self.mapping.get(text, f"EN[{text}]")


class TestTableSync(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def run_it(self, src, fake):
        out = self.dir / "out.xlsx"
        run_process(src, out, default_cfg(), fake)
        return read_zip(out)

    def test_table_sheet_mapping(self):
        src = build(self.dir / "in.xlsx", SHEET, ["名前", "数量"], ["名前", "数量"])
        with zipfile.ZipFile(src) as z:
            self.assertEqual(tb.table_sheets(z), {"xl/tables/table1.xml": "xl/worksheets/sheet1.xml"})

    def test_formulas_and_defined_names_follow_renamed_columns(self):
        src = build(self.dir / "in.xlsx", SHEET, ["名前", "数量"], ["名前", "数量"])
        parts = self.run_it(src, Mapped({"名前": "Name", "数量": "Qty"}))
        sheet = parse(parts["xl/worksheets/sheet1.xml"])
        formulas = [f.text for f in sheet.xpath("//m:f", namespaces=NSMAP)]
        self.assertEqual(formulas, ["T1[[#This Row],[Name]]*2", "SUM(T1[Qty])+T1[@Name]"])
        wb = parse(parts["xl/workbook.xml"])
        self.assertEqual(wb.xpath("//m:definedName", namespaces=NSMAP)[0].text, "T1[Name]")
        self.assertNotIn("名前".encode(), parts["xl/tables/table1.xml"])

    def test_unrelated_parts_stay_identical(self):
        src = build(self.dir / "in.xlsx", SHEET, ["名前", "数量"], ["名前", "数量"])
        before = read_zip(src)
        parts = self.run_it(src, Mapped({"名前": "Name", "数量": "Qty"}))
        self.assertEqual(parts["[Content_Types].xml"], before["[Content_Types].xml"])
        self.assertEqual(parts["xl/worksheets/_rels/sheet1.xml.rels"], before["xl/worksheets/_rels/sheet1.xml.rels"])

    def test_formula_without_renamed_columns_is_not_touched(self):
        plain = SHEET.replace("名前", "Name").replace("数量", "Qty")
        src = build(self.dir / "in.xlsx", plain, ["名前", "数量"], ["名前", "数量"])
        before = read_zip(src)
        parts = self.run_it(src, Mapped({"名前": "Name", "数量": "Qty"}))
        self.assertEqual(parts["xl/worksheets/sheet1.xml"], before["xl/worksheets/sheet1.xml"])

    def test_duplicate_translation_rewrites_header_cell_to_inline_string(self):
        src = build(self.dir / "in.xlsx", SHEET, ["名前", "備考"], ["名前", "備考"])
        parts = self.run_it(src, Mapped({"名前": "Remarks", "備考": "Remarks"}))
        names = [c.get("name") for c in parse(parts["xl/tables/table1.xml"]).xpath("//m:tableColumn", namespaces=NSMAP)]
        self.assertEqual(names, ["Remarks", "Remarks2"])
        sheet = parse(parts["xl/worksheets/sheet1.xml"])
        b1 = sheet.xpath("//m:c[@r='B1']", namespaces=NSMAP)[0]
        self.assertEqual(b1.get("t"), "inlineStr")
        self.assertEqual(b1.xpath("string(m:is/m:t)", namespaces=NSMAP), "Remarks2")
        self.assertIsNone(b1.find("{%s}v" % MAIN))
        a1 = sheet.xpath("//m:c[@r='A1']", namespaces=NSMAP)[0]
        self.assertEqual(a1.get("t"), "s")  # ô đầu tiên giữ nguyên

    def test_references_follow_deduped_names(self):
        src = build(self.dir / "in.xlsx", SHEET, ["名前", "数量"], ["名前", "数量"])
        parts = self.run_it(src, Mapped({"名前": "X", "数量": "X"}))
        formulas = [f.text for f in parse(parts["xl/worksheets/sheet1.xml"]).xpath("//m:f", namespaces=NSMAP)]
        self.assertEqual(formulas, ["T1[[#This Row],[X]]*2", "SUM(T1[X2])+T1[@X]"])

    def test_special_characters_in_new_name_are_escaped_in_formulas(self):
        src = build(self.dir / "in.xlsx", SHEET, ["名前", "数量"], ["名前", "数量"])
        parts = self.run_it(src, Mapped({"名前": "Name [no]", "数量": "Qty"}))
        formulas = [f.text for f in parse(parts["xl/worksheets/sheet1.xml"]).xpath("//m:f", namespaces=NSMAP)]
        self.assertEqual(formulas[0], "T1[[#This Row],[Name '[no']]]*2")


if __name__ == "__main__":
    unittest.main()
