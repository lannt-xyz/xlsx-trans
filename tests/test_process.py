"""Test toàn bộ luồng pipeline.process_xlsx trên file xlsx mẫu (Ollama được giả lập)."""
import json
import re
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from tests import fixtures as fx
from tests.fixtures import FakeTranslator, a_texts, default_cfg, read_zip, run_process, sst_texts
from xlsx_trans import pipeline
from xlsx_trans.cache import TranslationCache
from xlsx_trans.xlsx_xml import NSMAP, parse

try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None

EXPECTED_SST = [
    "EN[名前]", "EN[数量]", "EN[備考]", "EN[りんご]", "EN[新鮮です]",
    "ABC-123", "EN[1行目\n2行目]", "EN[良い|悪い]", "EN[合計]",
]


class ProcessTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.src = fx.build_fixture(self.dir / "in.xlsx")
        self.out = self.dir / "out.xlsx"
        self.cfg = default_cfg()
        self.src_parts = read_zip(self.src)

    def run_it(self, cfg=None, fake=None, out=None, **kw):
        return run_process(self.src, out or self.out, cfg or self.cfg, fake, **kw)

    def out_parts(self, path=None):
        return read_zip(path or self.out)


class TestTranslation(ProcessTestCase):
    def test_every_target_is_translated(self):
        (applied, errors), logs, fake = self.run_it()
        self.assertEqual((applied, errors), (fx.UNIT_COUNT, 0))
        parts = self.out_parts()

        self.assertEqual(sst_texts(parts[fx.P_SHARED]), EXPECTED_SST)

        sheet = parse(parts[fx.P_SHEET1])
        self.assertEqual(sheet.xpath("//m:c[@r='A3']/m:is/m:t", namespaces=NSMAP)[0].text, "EN[みかん]")
        self.assertEqual(sheet.xpath("//m:c[@r='B2']/m:v", namespaces=NSMAP)[0].text, "3")  # số giữ nguyên
        self.assertEqual(sheet.xpath("//m:c[@r='D3']/m:f", namespaces=NSMAP)[0].text, 'A2&"x"')  # công thức giữ nguyên
        self.assertEqual(sheet.xpath("//m:c[@r='D3']/m:v", namespaces=NSMAP)[0].text, "りんごx")

        comment = parse(parts[fx.P_COMMENTS])
        self.assertEqual([t.text or "" for t in comment.xpath("//m:t", namespaces=NSMAP)], ["EN[確認してください]", ""])

        # Choice + Fallback đều được dịch; đoạn tiếng Anh giữ nguyên
        self.assertEqual(a_texts(parts[fx.P_DRAWING]), ["EN[注意事項です]", "", "OK 123", "EN[注意事項です]"])
        self.assertEqual(a_texts(parts[fx.P_CHART]), ["EN[売上グラフ]"])
        self.assertEqual(a_texts(parts[fx.P_DIAGRAM]), ["EN[図表]"])

        table = parse(parts[fx.P_TABLE])
        self.assertEqual(
            [c.get("name") for c in table.xpath("//m:tableColumn", namespaces=NSMAP)],
            ["EN[名前]", "EN[数量]", "EN[備考]"],
        )

    def test_each_unique_string_is_translated_once(self):
        _, logs, fake = self.run_it()
        self.assertEqual(len(fake.calls), fx.UNIQUE_COUNT)
        self.assertEqual(len(set(fake.calls)), fx.UNIQUE_COUNT)
        self.assertTrue(any(f"{fx.UNIT_COUNT} đoạn" in l and f"{fx.UNIQUE_COUNT} chuỗi" in l for l in logs), logs)

    def test_rich_text_furigana_is_removed_and_runs_merged(self):
        self.run_it()
        root = parse(self.out_parts()[fx.P_SHARED])
        si = root.xpath("//m:si", namespaces=NSMAP)[4]
        self.assertEqual([t.text or "" for t in si.xpath("./m:r/m:t", namespaces=NSMAP)], ["EN[新鮮です]", ""])
        self.assertEqual(si.xpath("./m:rPh|./m:phoneticPr", namespaces=NSMAP), [])

    def test_source_pattern_decides_what_is_translated(self):
        self.cfg.src_re = re.compile("ABC")
        (applied, _), _, fake = self.run_it()
        self.assertEqual(fake.calls, ["ABC-123"])
        self.assertEqual(applied, 1)
        texts = sst_texts(self.out_parts()[fx.P_SHARED])
        self.assertEqual(texts[5], "EN[ABC-123]")
        self.assertEqual(texts[0], "名前")

    def test_bilingual_mode_uses_configured_separators(self):
        self.cfg.mode = "bilingual"
        self.cfg.cell_sep = " | "
        self.cfg.shape_sep = " - "
        self.run_it()
        parts = self.out_parts()
        texts = sst_texts(parts[fx.P_SHARED])
        self.assertEqual(texts[0], "名前 | EN[名前]")
        self.assertEqual(texts[4], "新鮮です | EN[新鮮です]")
        self.assertEqual(a_texts(parts[fx.P_DRAWING])[0], "注意事項です - EN[注意事項です]")
        self.assertEqual(a_texts(parts[fx.P_CHART]), ["売上グラフ - EN[売上グラフ]"])
        comment = parse(parts[fx.P_COMMENTS]).xpath("//m:t", namespaces=NSMAP)[0].text
        self.assertEqual(comment, "確認してください | EN[確認してください]")

    def test_bilingual_newline_in_table_names_is_escaped(self):
        self.cfg.mode = "bilingual"  # cell_sep mặc định là "\n"
        self.run_it()
        table = parse(self.out_parts()[fx.P_TABLE])
        names = [c.get("name") for c in table.xpath("//m:tableColumn", namespaces=NSMAP)]
        self.assertEqual(names[0], "名前_x000a_EN[名前]")

    def test_table_names_made_unique_when_translations_collide(self):
        class Same(FakeTranslator):
            def __call__(self, text, cfg):
                self.calls.append(text)
                return "Same"

        self.run_it(fake=Same())
        table = parse(self.out_parts()[fx.P_TABLE])
        names = [c.get("name") for c in table.xpath("//m:tableColumn", namespaces=NSMAP)]
        self.assertEqual(names, ["Same", "Same2", "Same3"])


class TestPreservation(ProcessTestCase):
    def test_parts_without_japanese_are_byte_identical_and_order_kept(self):
        self.run_it()
        out = self.out_parts()
        self.assertEqual(list(out), list(self.src_parts))
        for name, data in self.src_parts.items():
            if name in fx.TRANSLATED_PARTS:
                self.assertNotEqual(out[name], data, name)
            else:
                self.assertEqual(out[name], data, name)

    def test_compression_types_are_preserved(self):
        self.run_it()
        with zipfile.ZipFile(self.src) as a, zipfile.ZipFile(self.out) as b:
            self.assertEqual(
                [(i.filename, i.compress_type) for i in a.infolist()],
                [(i.filename, i.compress_type) for i in b.infolist()],
            )

    def test_input_file_is_not_modified(self):
        before = self.src.read_bytes()
        self.run_it()
        self.assertEqual(self.src.read_bytes(), before)

    def test_translated_parts_keep_xml_declaration_and_namespaces(self):
        self.run_it()
        draw = self.out_parts()[fx.P_DRAWING]
        self.assertTrue(draw.startswith(b"<?xml"))
        for token in (b"xdr:wsDr", b"mc:AlternateContent", b"mc:Fallback"):
            self.assertIn(token, draw)
        self.assertNotIn(b"ns0:", draw)

    def test_file_without_japanese_is_copied_unchanged(self):
        src = self.dir / "plain.xlsx"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("[Content_Types].xml", fx.fixture_parts()["[Content_Types].xml"])
            z.writestr("xl/sharedStrings.xml", fx._p(f'<sst xmlns="{fx.MAIN}"><si><t>Hello</t></si></sst>'))
        (applied, errors), _, fake = run_process(src, self.dir / "plain_out.xlsx", self.cfg)
        self.assertEqual((applied, errors, fake.calls), (0, 0, []))
        self.assertEqual(read_zip(self.dir / "plain_out.xlsx"), read_zip(src))

    @unittest.skipUnless(openpyxl, "cần openpyxl")
    def test_output_opens_with_openpyxl(self):
        self.run_it()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(self.out, data_only=True)
        ws = wb["売上"]
        self.assertEqual(ws["A1"].value, "EN[名前]")
        self.assertEqual(ws["B2"].value, 3)
        self.assertEqual(ws["C2"].value, "EN[新鮮です]")
        self.assertEqual(ws["A3"].value, "EN[みかん]")
        self.assertEqual(ws["A2"].comment.text, "EN[確認してください]")
        self.assertEqual([c.name for c in ws.tables["T1"].tableColumns], ["EN[名前]", "EN[数量]", "EN[備考]"])
        self.assertEqual(wb["Summary"]["B3"].value, "EN[合計]")


class TestTargets(ProcessTestCase):
    FLAG_PARTS = {
        "cells": {fx.P_SHARED, fx.P_SHEET1, fx.P_TABLE},  # tên cột Table đi cùng ô tiêu đề
        "shapes": {fx.P_DRAWING},
        "charts": {fx.P_CHART},
        "diagrams": {fx.P_DIAGRAM},
        "comments": {fx.P_COMMENTS},
    }

    def test_each_flag_off_leaves_its_parts_untouched_and_others_translated(self):
        from xlsx_trans import config

        self.assertEqual(set(self.FLAG_PARTS), set(config.DEFAULT_CONFIG["targets"]) - {"table_headers"})
        for flag, off_parts in self.FLAG_PARTS.items():
            with self.subTest(flag=flag):
                cfg = default_cfg()
                cfg.targets[flag] = False
                out = self.dir / f"out_{flag}.xlsx"
                self.run_it(cfg=cfg, out=out)
                parts = read_zip(out)
                for name in off_parts:
                    self.assertEqual(parts[name], self.src_parts[name], name)
                for name in fx.TRANSLATED_PARTS - off_parts:
                    self.assertNotEqual(parts[name], self.src_parts[name], name)

    def test_all_flags_off_translates_nothing(self):
        for k in self.cfg.targets:
            self.cfg.targets[k] = False
        (applied, errors), logs, fake = self.run_it()
        self.assertEqual((applied, errors, fake.calls), (0, 0, []))
        self.assertEqual(self.out_parts(), self.src_parts)
        self.assertTrue(any("0 đoạn" in l for l in logs))


class TestTableConsistency(ProcessTestCase):
    """Excel báo file lỗi nếu ô tiêu đề Table khác tên cột; các test dưới đây giữ hai thứ này khớp nhau."""

    def header_pairs(self, parts):
        from xlsx_trans.tables import split_ref  # noqa: F401

        shared = sst_texts(parts[fx.P_SHARED])
        sheet = parse(parts[fx.P_SHEET1])
        cells = []
        for addr in ("A1", "B1", "C1"):
            c = sheet.xpath(f"//m:c[@r='{addr}']", namespaces=NSMAP)[0]
            if c.get("t") == "s":
                cells.append(shared[int(c.find("{%s}v" % fx.MAIN).text)])
            else:
                cells.append("".join(t.text or "" for t in c.iter("{%s}t" % fx.MAIN)))
        names = [c.get("name") for c in parse(parts[fx.P_TABLE]).xpath("//m:tableColumn", namespaces=NSMAP)]
        return cells, names

    def test_header_cells_equal_column_names_normally(self):
        self.run_it()
        cells, names = self.header_pairs(self.out_parts())
        self.assertEqual(cells, names)

    def test_colliding_translations_keep_headers_and_names_equal(self):
        class Same(FakeTranslator):
            def __call__(self, text, cfg):
                self.calls.append(text)
                return "Same"

        self.run_it(fake=Same())
        cells, names = self.header_pairs(self.out_parts())
        self.assertEqual(names, ["Same", "Same2", "Same3"])
        self.assertEqual(cells, names)

    def test_bilingual_headers_match(self):
        self.cfg.mode = "bilingual"
        self.run_it()
        cells, names = self.header_pairs(self.out_parts())
        self.assertEqual([n.replace("_x000a_", "\n") for n in names], cells)

    def test_cells_off_leaves_table_alone(self):
        self.cfg.targets["cells"] = False
        self.cfg.targets["table_headers"] = False
        self.run_it()
        self.assertEqual(self.out_parts()[fx.P_TABLE], self.src_parts[fx.P_TABLE])


class TestExcelStrictness(ProcessTestCase):
    def test_drawingml_text_has_no_xml_space_attribute(self):
        self.run_it()
        for name in (fx.P_DRAWING, fx.P_CHART, fx.P_DIAGRAM):
            self.assertNotIn(b"xml:space", self.out_parts()[name], name)

    def test_spreadsheetml_text_keeps_xml_space(self):
        self.run_it()
        self.assertIn(b'xml:space="preserve"', self.out_parts()[fx.P_SHARED])

    def test_xml_declaration_uses_double_quotes(self):
        self.run_it()
        for name in fx.TRANSLATED_PARTS:
            self.assertTrue(
                self.out_parts()[name].startswith(b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'), name
            )

    def test_zip_entries_have_no_stale_extra_fields(self):
        with zipfile.ZipFile(self.src) as z:  # gắn extra field + cờ vào file gốc để chắc chắn không bị chép sang
            pass
        self.run_it()
        with zipfile.ZipFile(self.out) as z:
            self.assertIsNone(z.testzip())
            for i in z.infolist():
                self.assertEqual(i.extra, b"", i.filename)
                self.assertEqual(i.flag_bits & 0x08, 0, i.filename)

    def test_all_output_parts_are_well_formed_xml(self):
        from lxml import etree

        self.run_it()
        for name, data in self.out_parts().items():
            if name.endswith((".xml", ".rels", ".vml")):
                etree.fromstring(data)


class TestCache(ProcessTestCase):
    @property
    def cache_path(self):
        return Path(str(self.out) + ".cache.json")

    def test_cache_file_is_written_with_signature_and_map(self):
        self.run_it()
        data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertEqual(data["sig"], self.cfg.signature())
        self.assertEqual(len(data["map"]), fx.UNIQUE_COUNT)
        self.assertEqual(data["map"]["りんご"], "EN[りんご]")

    def test_second_run_reuses_cache_without_calling_the_model(self):
        self.run_it()
        first = self.out_parts()
        _, logs, fake = self.run_it()
        self.assertEqual(fake.calls, [])
        self.assertTrue(any(f"Dùng lại {fx.UNIQUE_COUNT}" in l for l in logs), logs)
        self.assertEqual(self.out_parts(), first)

    def test_changing_prompt_model_or_options_invalidates_cache(self):
        self.run_it()
        for change in (
            {"system_prompt": "khác"},
            {"user_template": "X {text}"},
            {"model": "other"},
            {"options": {"temperature": 1}},
        ):
            with self.subTest(change=change):
                cfg = default_cfg(**change)
                _, _, fake = self.run_it(cfg=cfg)
                self.assertEqual(len(fake.calls), fx.UNIQUE_COUNT)

    def test_changing_host_or_mode_keeps_cache(self):
        self.run_it()
        cfg = default_cfg(host="http://other:1", mode="bilingual")
        _, _, fake = self.run_it(cfg=cfg)
        self.assertEqual(fake.calls, [])

    def test_cache_disabled_writes_and_reads_nothing(self):
        self.cfg.cache = False
        self.run_it()
        self.assertFalse(self.cache_path.exists())
        _, _, fake = self.run_it()
        self.assertEqual(len(fake.calls), fx.UNIQUE_COUNT)

    def test_corrupt_cache_is_ignored(self):
        self.cache_path.write_text("{không phải json", encoding="utf-8")
        _, _, fake = self.run_it()
        self.assertEqual(len(fake.calls), fx.UNIQUE_COUNT)

    def test_stop_then_resume_translates_only_the_remainder(self):
        fake1 = FakeTranslator()
        (applied, _), logs, _ = self.run_it(fake=fake1, should_stop=lambda: len(fake1.calls) >= 3)
        self.assertEqual(len(fake1.calls), 3)
        self.assertLess(applied, fx.UNIT_COUNT)
        self.assertTrue(any("Đã dừng" in l for l in logs))
        texts = sst_texts(self.out_parts()[fx.P_SHARED])
        self.assertEqual(texts[:4], ["EN[名前]", "EN[数量]", "EN[備考]", "りんご"])  # phần chưa dịch giữ nguyên

        fake2 = FakeTranslator()
        (applied2, _), _, _ = self.run_it(fake=fake2)
        self.assertEqual(len(fake2.calls), fx.UNIQUE_COUNT - 3)
        self.assertFalse(set(fake1.calls) & set(fake2.calls))
        self.assertEqual(applied2, fx.UNIT_COUNT)
        self.assertEqual(sst_texts(self.out_parts()[fx.P_SHARED]), EXPECTED_SST)

    def test_injected_cache_is_shared_between_files_and_not_written_next_to_output(self):
        cache = TranslationCache(None, self.cfg.signature())  # chỉ trong bộ nhớ
        _, _, fake1 = self.run_it(cache=cache)
        self.assertEqual(len(fake1.calls), fx.UNIQUE_COUNT)
        _, logs2, fake2 = self.run_it(cache=cache, out=self.dir / "out2.xlsx")
        self.assertEqual(fake2.calls, [])
        self.assertTrue(any("Dùng lại" in l for l in logs2))
        self.assertFalse(self.cache_path.exists())


class TestOutputLocations(ProcessTestCase):
    def test_output_parent_directories_are_created(self):
        out = self.dir / "n1" / "n2" / "out.xlsx"
        self.run_it(out=out)
        self.assertTrue(out.exists())

    def test_markdown_default_path_is_next_to_output(self):
        cfg = default_cfg(md=True)
        self.run_it(cfg=cfg)
        self.assertTrue(self.out.with_suffix(".md").exists())

    @unittest.skipUnless(openpyxl, "cần openpyxl")
    def test_custom_markdown_path_with_new_directories(self):
        cfg = default_cfg(md=True)
        md = self.dir / "md" / "deep" / "x.md"
        self.run_it(cfg=cfg, md_path=md)
        self.assertTrue(md.exists())
        self.assertFalse(self.out.with_suffix(".md").exists())

    def test_log_header_can_be_suppressed(self):
        self.cfg.warnings = ["w"]
        _, logs, _ = self.run_it(log_header=False)
        self.assertFalse(any(l.startswith(("Cấu hình:", "Cảnh báo:")) for l in logs))


class TestErrorsAndCallbacks(ProcessTestCase):
    def test_translation_failure_keeps_original_text_and_is_counted(self):
        fake = FakeTranslator(fail_on={"りんご"})
        (applied, errors), logs, _ = self.run_it(fake=fake)
        self.assertEqual(errors, 1)
        self.assertEqual(applied, fx.UNIT_COUNT - 1)
        self.assertEqual(sst_texts(self.out_parts()[fx.P_SHARED])[3], "りんご")
        self.assertTrue(any("Lỗi với đoạn" in l and "りんご" in l for l in logs), logs)
        data = json.loads(Path(str(self.out) + ".cache.json").read_text(encoding="utf-8"))
        self.assertNotIn("りんご", data["map"])

    def test_progress_callback(self):
        calls = []
        self.run_it(progress=lambda d, t: calls.append((d, t)))
        self.assertEqual(calls[0], (0, fx.UNIQUE_COUNT))
        self.assertEqual(calls[-1], (fx.UNIQUE_COUNT, fx.UNIQUE_COUNT))
        self.assertEqual([d for d, _ in calls], sorted(d for d, _ in calls))

    def test_logs_config_summary_and_warnings(self):
        self.cfg.warnings = ["prompt thiếu"]
        self.cfg.model = "model-x"
        _, logs, _ = self.run_it()
        self.assertIn("Cảnh báo: prompt thiếu", logs)
        self.assertTrue(any(l.startswith("Cấu hình:") and "model-x" in l for l in logs), logs)

    def test_output_must_differ_from_input(self):
        with self.assertRaisesRegex(ValueError, "khác"):
            pipeline.process_xlsx(self.src, self.src, self.cfg)

    def test_unsupported_extension(self):
        with self.assertRaisesRegex(ValueError, "xlsx"):
            pipeline.process_xlsx(self.dir / "old.xls", self.dir / "o.xlsx", self.cfg)

    def test_corrupt_file_raises_bad_zip(self):
        bad = self.dir / "bad.xlsx"
        bad.write_bytes(b"khong phai zip")
        with self.assertRaises(zipfile.BadZipFile):
            pipeline.process_xlsx(bad, self.dir / "o.xlsx", self.cfg, log=lambda m: None)

    def test_default_out(self):
        self.assertEqual(pipeline.default_out("/a/b/report.xlsx", self.cfg), str(Path("/a/b/report_en.xlsx")))
        cfg = default_cfg(suffix="_vi")
        self.assertEqual(pipeline.default_out("x.XLSM", cfg), "x_vi.XLSM")


if __name__ == "__main__":
    unittest.main()
