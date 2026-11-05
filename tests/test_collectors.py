"""Test các hàm gom/áp bản dịch trên các đoạn XML nhỏ."""
import re
import unittest

from tests.fixtures import DML, MAIN
import app

RX = re.compile(app.JP_PATTERN)


def parse(xml):
    return app._parse(xml.encode("utf-8"))


class TestCollectSml(unittest.TestCase):
    def collect(self, xml, sep="\n"):
        root = parse(xml)
        units = []
        app._collect_sml(root.xpath("//m:si", namespaces=app.NSMAP), units, RX, sep)
        return root, units

    def test_plain_japanese_string_is_collected_and_english_skipped(self):
        _, units = self.collect(f'<sst xmlns="{MAIN}"><si><t>りんご</t></si><si><t>ABC-123</t></si><si/></sst>')
        self.assertEqual([u[0] for u in units], ["りんご"])

    def test_rich_text_runs_are_joined_and_furigana_excluded_from_text(self):
        _, units = self.collect(
            f'<sst xmlns="{MAIN}"><si><r><t>新</t></r><r><t>鮮</t></r>'
            '<rPh sb="0" eb="1"><t>シン</t></rPh><phoneticPr fontId="0"/></si></sst>'
        )
        self.assertEqual(units[0][0], "新鮮")

    def test_setter_puts_translation_in_first_run_and_drops_furigana(self):
        root, units = self.collect(
            f'<sst xmlns="{MAIN}"><si><r><t>新</t></r><r><t>鮮</t></r>'
            '<rPh sb="0" eb="1"><t>シン</t></rPh><phoneticPr fontId="0"/></si></sst>'
        )
        units[0][2]("Fresh")
        ts = root.xpath("//m:si/m:r/m:t", namespaces=app.NSMAP)
        self.assertEqual([t.text for t in ts], ["Fresh", ""])
        self.assertEqual(ts[0].get(app.XML_SPACE), "preserve")
        self.assertEqual(root.xpath("//m:rPh|//m:phoneticPr", namespaces=app.NSMAP), [])

    def test_unit_carries_the_separator(self):
        _, units = self.collect(f'<sst xmlns="{MAIN}"><si><t>日本</t></si></sst>', sep=" | ")
        self.assertEqual(units[0][1], " | ")

    def test_inline_string_container(self):
        root = parse(f'<worksheet xmlns="{MAIN}"><sheetData><row><c t="inlineStr"><is><t>日本</t></is></c></row></sheetData></worksheet>')
        units = []
        app._collect_sml(root.xpath("//m:c[@t='inlineStr']/m:is", namespaces=app.NSMAP), units, RX, "\n")
        units[0][2]("Japan")
        self.assertEqual(root.xpath("//m:is/m:t", namespaces=app.NSMAP)[0].text, "Japan")


class TestCollectDrawingml(unittest.TestCase):
    def collect(self, body):
        root = parse(f'<r xmlns:a="{DML}">{body}</r>')
        units = []
        app._collect_drawingml(root, units, RX, " / ")
        return root, units

    def test_runs_of_one_paragraph_are_one_unit(self):
        _, units = self.collect("<a:p><a:r><a:t>日本</a:t></a:r><a:r><a:t>語</a:t></a:r></a:p>")
        self.assertEqual([u[0] for u in units], ["日本語"])

    def test_paragraphs_without_japanese_or_runs_are_skipped(self):
        _, units = self.collect(
            "<a:p><a:r><a:t>Hello</a:t></a:r></a:p><a:p><a:endParaRPr/></a:p><a:p><a:r><a:t>日本</a:t></a:r></a:p>"
        )
        self.assertEqual([u[0] for u in units], ["日本"])

    def test_setter_writes_first_run_and_clears_the_rest(self):
        root, units = self.collect("<a:p><a:r><a:t>日本</a:t></a:r><a:r><a:t>語</a:t></a:r></a:p>")
        units[0][2]("Japanese")
        self.assertEqual([t.text for t in root.iter(app.A + "t")], ["Japanese", ""])


class TestTables(unittest.TestCase):
    def collect(self, names):
        cols = "".join(f'<tableColumn id="{i}" name="{n}"/>' for i, n in enumerate(names, 1))
        root = parse(f'<table xmlns="{MAIN}"><tableColumns count="{len(names)}">{cols}</tableColumns></table>')
        units, post = [], []
        app._collect_table(root, post, units, RX, "\n")
        return root, units, post

    def names(self, root):
        return [c.get("name") for c in root.xpath("//m:tableColumn", namespaces=app.NSMAP)]

    def test_only_japanese_names_are_collected(self):
        _, units, post = self.collect(["名前", "Qty", "備考"])
        self.assertEqual([u[0] for u in units], ["名前", "備考"])
        self.assertEqual(len(post), 1)

    def test_newline_escape_is_decoded_and_encoded(self):
        root, units, _ = self.collect(["名前_x000a_ラベル"])
        self.assertEqual(units[0][0], "名前\nラベル")
        units[0][2]("Name\nLabel")
        self.assertEqual(self.names(root), ["Name_x000a_Label"])

    def test_table_without_columns_is_ignored(self):
        root = parse(f'<table xmlns="{MAIN}"/>')
        units, post = [], []
        app._collect_table(root, post, units, RX, "\n")
        self.assertEqual((units, post), ([], []))

    def test_duplicate_names_are_made_unique_case_insensitively(self):
        root, _, post = self.collect(["A", "a", "A"])
        app._dedupe_table_names(post)
        self.assertEqual(self.names(root), ["A", "a2", "A3"])

    def test_unique_names_are_left_alone(self):
        root, _, post = self.collect(["X", "Y", "Z"])
        app._dedupe_table_names(post)
        self.assertEqual(self.names(root), ["X", "Y", "Z"])


class TestSerialize(unittest.TestCase):
    def test_roundtrip_keeps_prefixes_declaration_and_standalone(self):
        src = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<r xmlns:a="{DML}"><a:p/></r>'.encode()
        out = app._serialize(app._parse(src))
        self.assertTrue(out.startswith(b"<?xml"))
        self.assertIn(b"standalone='yes'", out.replace(b'"', b"'"))
        self.assertIn(b"<a:p/>", out)
        self.assertNotIn(b"ns0", out)


if __name__ == "__main__":
    unittest.main()
