"""Test gom/áp bản dịch trên XML (xlsx_xml): từng đoạn nhỏ và quét cả package mẫu."""
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests import fixtures as fx
from tests.fixtures import DML, MAIN, default_cfg
from xlsx_trans import config, xlsx_xml
from xlsx_trans.xlsx_xml import A, NSMAP, XML_SPACE

RX = re.compile(config.JP_PATTERN)


def parse(xml):
    return xlsx_xml.parse(xml.encode("utf-8"))


class TestCollectSml(unittest.TestCase):
    def collect(self, xml, sep="\n"):
        root = parse(xml)
        units = []
        xlsx_xml.collect_sml(root.xpath("//m:si", namespaces=NSMAP), units, RX, sep)
        return root, units

    def test_plain_japanese_string_is_collected_and_english_skipped(self):
        _, units = self.collect(f'<sst xmlns="{MAIN}"><si><t>りんご</t></si><si><t>ABC-123</t></si><si/></sst>')
        self.assertEqual([u.text for u in units], ["りんご"])

    def test_rich_text_runs_are_joined_and_furigana_excluded_from_text(self):
        _, units = self.collect(
            f'<sst xmlns="{MAIN}"><si><r><t>新</t></r><r><t>鮮</t></r>'
            '<rPh sb="0" eb="1"><t>シン</t></rPh><phoneticPr fontId="0"/></si></sst>'
        )
        self.assertEqual(units[0].text, "新鮮")

    def test_apply_puts_translation_in_first_run_and_drops_furigana(self):
        root, units = self.collect(
            f'<sst xmlns="{MAIN}"><si><r><t>新</t></r><r><t>鮮</t></r>'
            '<rPh sb="0" eb="1"><t>シン</t></rPh><phoneticPr fontId="0"/></si></sst>'
        )
        units[0].apply("Fresh")
        ts = root.xpath("//m:si/m:r/m:t", namespaces=NSMAP)
        self.assertEqual([t.text for t in ts], ["Fresh", ""])
        self.assertEqual(ts[0].get(XML_SPACE), "preserve")
        self.assertEqual(root.xpath("//m:rPh|//m:phoneticPr", namespaces=NSMAP), [])

    def test_unit_carries_the_separator(self):
        _, units = self.collect(f'<sst xmlns="{MAIN}"><si><t>日本</t></si></sst>', sep=" | ")
        self.assertEqual(units[0].sep, " | ")

    def test_unit_is_a_named_tuple(self):
        _, units = self.collect(f'<sst xmlns="{MAIN}"><si><t>日本</t></si></sst>')
        text, sep, apply = units[0]
        self.assertEqual((text, sep), ("日本", "\n"))
        self.assertTrue(callable(apply))

    def test_inline_string_container(self):
        root = parse(f'<worksheet xmlns="{MAIN}"><sheetData><row><c t="inlineStr"><is><t>日本</t></is></c></row></sheetData></worksheet>')
        units = []
        xlsx_xml.collect_sml(root.xpath("//m:c[@t='inlineStr']/m:is", namespaces=NSMAP), units, RX, "\n")
        units[0].apply("Japan")
        self.assertEqual(root.xpath("//m:is/m:t", namespaces=NSMAP)[0].text, "Japan")


class TestCollectDrawingml(unittest.TestCase):
    def collect(self, body):
        root = parse(f'<r xmlns:a="{DML}">{body}</r>')
        units = []
        xlsx_xml.collect_drawingml(root, units, RX, " / ")
        return root, units

    def test_runs_of_one_paragraph_are_one_unit(self):
        _, units = self.collect("<a:p><a:r><a:t>日本</a:t></a:r><a:r><a:t>語</a:t></a:r></a:p>")
        self.assertEqual([u.text for u in units], ["日本語"])

    def test_paragraphs_without_japanese_or_runs_are_skipped(self):
        _, units = self.collect(
            "<a:p><a:r><a:t>Hello</a:t></a:r></a:p><a:p><a:endParaRPr/></a:p><a:p><a:r><a:t>日本</a:t></a:r></a:p>"
        )
        self.assertEqual([u.text for u in units], ["日本"])

    def test_apply_writes_first_run_and_clears_the_rest(self):
        root, units = self.collect("<a:p><a:r><a:t>日本</a:t></a:r><a:r><a:t>語</a:t></a:r></a:p>")
        units[0].apply("Japanese")
        self.assertEqual([t.text for t in root.iter(A + "t")], ["Japanese", ""])


class TestTables(unittest.TestCase):
    def collect(self, names):
        cols = "".join(f'<tableColumn id="{i}" name="{n}"/>' for i, n in enumerate(names, 1))
        root = parse(f'<table xmlns="{MAIN}"><tableColumns count="{len(names)}">{cols}</tableColumns></table>')
        units, tables = [], []
        xlsx_xml.collect_table(root, tables, units, RX, "\n")
        return root, units, tables

    def names(self, root):
        return [c.get("name") for c in root.xpath("//m:tableColumn", namespaces=NSMAP)]

    def test_only_japanese_names_are_collected(self):
        _, units, tables = self.collect(["名前", "Qty", "備考"])
        self.assertEqual([u.text for u in units], ["名前", "備考"])
        self.assertEqual(len(tables), 1)

    def test_newline_escape_is_decoded_and_encoded(self):
        root, units, _ = self.collect(["名前_x000a_ラベル"])
        self.assertEqual(units[0].text, "名前\nラベル")
        units[0].apply("Name\nLabel")
        self.assertEqual(self.names(root), ["Name_x000a_Label"])

    def test_table_without_columns_is_ignored(self):
        root = parse(f'<table xmlns="{MAIN}"/>')
        units, tables = [], []
        xlsx_xml.collect_table(root, tables, units, RX, "\n")
        self.assertEqual((units, tables), ([], []))

    def test_duplicate_names_are_made_unique_case_insensitively(self):
        root, _, tables = self.collect(["A", "a", "A"])
        xlsx_xml.dedupe_table_names(tables)
        self.assertEqual(self.names(root), ["A", "a2", "A3"])

    def test_unique_names_are_left_alone(self):
        root, _, tables = self.collect(["X", "Y", "Z"])
        xlsx_xml.dedupe_table_names(tables)
        self.assertEqual(self.names(root), ["X", "Y", "Z"])


class TestSerialize(unittest.TestCase):
    def test_roundtrip_keeps_prefixes_declaration_and_standalone(self):
        src = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<r xmlns:a="{DML}"><a:p/></r>'.encode()
        out = xlsx_xml.serialize(xlsx_xml.parse(src))
        self.assertTrue(out.startswith(b"<?xml"))
        self.assertIn(b"standalone='yes'", out.replace(b'"', b"'"))
        self.assertIn(b"<a:p/>", out)
        self.assertNotIn(b"ns0", out)


class TestCollectPartsAndWritePackage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.src = fx.build_fixture(self.dir / "in.xlsx")

    def test_collects_every_target_and_only_parts_with_text(self):
        cfg = default_cfg()
        with zipfile.ZipFile(self.src) as z:
            units, parsed, tables = xlsx_xml.collect_parts(z, z.infolist(), cfg)
        self.assertEqual(len(units), fx.UNIT_COUNT)
        self.assertEqual(set(parsed), fx.TRANSLATED_PARTS)
        self.assertEqual(len(tables), 1)

    def test_target_flags_exclude_parts(self):
        cfg = default_cfg()
        cfg.targets["shapes"] = cfg.targets["charts"] = cfg.targets["diagrams"] = False
        with zipfile.ZipFile(self.src) as z:
            _, parsed, _ = xlsx_xml.collect_parts(z, z.infolist(), cfg)
        self.assertEqual(set(parsed), fx.TRANSLATED_PARTS - {fx.P_DRAWING, fx.P_CHART, fx.P_DIAGRAM})

    def test_write_package_without_changes_reproduces_every_part(self):
        out = self.dir / "copy.xlsx"
        with zipfile.ZipFile(self.src) as z:
            xlsx_xml.write_package(z, z.infolist(), out, {})
        self.assertEqual(fx.read_zip(out), fx.read_zip(self.src))

    def test_write_package_replaces_only_given_parts(self):
        out = self.dir / "copy.xlsx"
        with zipfile.ZipFile(self.src) as z:
            infos = z.infolist()
            root = xlsx_xml.parse(z.read(fx.P_CHART))
            next(root.iter(A + "t")).text = "Changed"
            xlsx_xml.write_package(z, infos, out, {fx.P_CHART: root})
        new, old = fx.read_zip(out), fx.read_zip(self.src)
        self.assertEqual({n for n in old if old[n] != new[n]}, {fx.P_CHART})
        self.assertIn("Changed".encode(), new[fx.P_CHART])


if __name__ == "__main__":
    unittest.main()
