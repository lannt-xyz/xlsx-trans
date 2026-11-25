"""Từ điển giữ nguyên tiếng Nhật: đọc/ghi file, bảo vệ từ khi dịch, tích hợp vào pipeline và CLI."""
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import fixtures as fx
from tests.fixtures import FakeTranslator, default_cfg, patch_translate, read_zip, run_process, sst_texts
from xlsx_trans import backend, cli, config, dictionary
from xlsx_trans.dictionary import Dictionary

RX = re.compile(config.JP_PATTERN)


class TestParse(unittest.TestCase):
    def test_sections_comments_blank_lines_and_default_category(self):
        d = Dictionary.parse("# ghi chú\n\n山田\n[screen]\nログイン画面\n  受注一覧  \n[person]\n鈴木\n")
        self.assertEqual(d.entries, {"other": ["山田"], "screen": ["ログイン画面", "受注一覧"], "person": ["鈴木"]})

    def test_duplicates_in_a_category_are_dropped(self):
        d = Dictionary.parse("[a]\nX\nX\n")
        self.assertEqual(d.entries, {"a": ["X"]})

    def test_terms_sorted_longest_first_and_deduped_across_categories(self):
        d = Dictionary.parse("[a]\nログイン\nログイン画面\n[b]\nログイン\n")
        self.assertEqual(d.terms(), ["ログイン画面", "ログイン"])
        self.assertEqual(len(d), 2)

    def test_empty_is_falsy(self):
        self.assertFalse(Dictionary())
        self.assertFalse(Dictionary.parse("# chỉ ghi chú\n[a]\n"))

    def test_category_of(self):
        d = Dictionary.parse("[screen]\nA画面\n")
        self.assertEqual(d.category_of("A画面"), "screen")
        self.assertIsNone(d.category_of("x"))

    def test_signature_changes_with_content_not_order_or_category(self):
        a = Dictionary.parse("[x]\nA\nB\n").signature()
        self.assertEqual(a, Dictionary.parse("[y]\nB\nA\n").signature())
        self.assertNotEqual(a, Dictionary.parse("[x]\nA\n").signature())


class TestLoadAndAdd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_load_merges_files_and_reports_missing(self):
        (self.dir / "a.txt").write_text("[s]\nA\n", encoding="utf-8")
        (self.dir / "b.txt").write_text("[s]\nB\n[p]\nC\n", encoding="utf-8-sig")
        missing = []
        d = Dictionary.load([self.dir / "a.txt", self.dir / "b.txt", self.dir / "none.txt"], missing)
        self.assertEqual(d.entries, {"s": ["A", "B"], "p": ["C"]})
        self.assertEqual(missing, [str(self.dir / "none.txt")])

    def test_add_term_creates_file_and_section(self):
        p = self.dir / "sub" / "d.txt"
        self.assertTrue(dictionary.add_term(p, "person", "山田太郎"))
        self.assertEqual(p.read_text(encoding="utf-8"), "[person]\n山田太郎\n")

    def test_add_term_inserts_into_existing_section_and_keeps_comments(self):
        p = self.dir / "d.txt"
        p.write_text("# ghi chú\n[screen]\nA\n\n[person]\nP\n", encoding="utf-8")
        dictionary.add_term(p, "screen", "B")
        dictionary.add_term(p, "new", "N")
        self.assertEqual(p.read_text(encoding="utf-8"), "# ghi chú\n[screen]\nA\nB\n\n[person]\nP\n\n[new]\nN\n")
        self.assertEqual(Dictionary.load([p]).entries, {"screen": ["A", "B"], "person": ["P"], "new": ["N"]})

    def test_add_existing_term_is_noop(self):
        p = self.dir / "d.txt"
        dictionary.add_term(p, "a", "X")
        before = p.read_text(encoding="utf-8")
        self.assertFalse(dictionary.add_term(p, "a", "X"))
        self.assertEqual(p.read_text(encoding="utf-8"), before)
        self.assertTrue(dictionary.add_term(p, "b", "X"))  # nhóm khác thì vẫn thêm

    def test_invalid_terms(self):
        p = self.dir / "d.txt"
        for bad in ("", "  ", "a\nb", "[x]"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    dictionary.add_term(p, "a", bad)


class TestProtect(unittest.TestCase):
    def setUp(self):
        self.d = Dictionary.parse("[s]\nログイン画面\nログイン\n[p]\n山田太郎\n")

    def test_longest_term_wins_and_same_term_shares_one_id(self):
        masked, mapping = self.d.protect("ログイン画面でログインし、ログイン画面を閉じる")
        self.assertEqual(masked, "[[1]]で[[2]]し、[[1]]を閉じる")
        self.assertEqual(mapping, {1: "ログイン画面", 2: "ログイン"})

    def test_no_match(self):
        self.assertEqual(self.d.protect("こんにちは"), ("こんにちは", {}))

    def test_restore_ok_tolerates_spaces_inside_brackets(self):
        _, mapping = self.d.protect("山田太郎さんが承認")
        self.assertEqual(Dictionary.restore("Approved by [[ 1 ]]", mapping), ("Approved by 山田太郎", True))

    def test_restore_fails_when_placeholder_missing_or_unknown(self):
        mapping = {1: "A", 2: "B"}
        self.assertFalse(Dictionary.restore("only [[1]]", mapping)[1])
        self.assertFalse(Dictionary.restore("[[1]] [[2]] [[3]]", mapping)[1])

    def test_needs_translation(self):
        self.assertFalse(self.d.needs_translation("ログイン画面", RX))
        self.assertFalse(self.d.needs_translation("ログイン画面 / 山田太郎 (2)", RX))
        self.assertTrue(self.d.needs_translation("ログイン画面を開く", RX))
        self.assertTrue(self.d.needs_translation("こんにちは", RX))
        self.assertFalse(self.d.needs_translation("ABC", RX))


class Echo:
    """Model giả: trả "EN{...}" bao quanh text nhận được, giữ nguyên [[n]]."""

    def __init__(self, drop_placeholders_times=0):
        self.calls = []
        self.drop = drop_placeholders_times

    def __call__(self, text, cfg):
        self.calls.append((text, cfg.system_prompt))
        if self.drop > 0:
            self.drop -= 1
            return "EN without placeholders"
        return f"EN<{text}>"


class TestBackendTranslate(unittest.TestCase):
    def cfg(self, text="[s]\nログイン画面\n[p]\n山田太郎\n"):
        cfg = default_cfg(system_prompt="SYS")
        cfg.dictionary = Dictionary.parse(text)
        return cfg

    def test_without_dictionary_text_goes_through_unchanged(self):
        cfg = default_cfg()
        fake = Echo()
        with patch_translate(fake):
            self.assertEqual(backend.translate_text("ログイン画面", cfg), "EN<ログイン画面>")

    def test_term_is_masked_for_the_model_and_restored_after(self):
        cfg, fake = self.cfg(), Echo()
        with patch_translate(fake):
            out = backend.translate_text("山田太郎がログイン画面を開く", cfg)
        self.assertEqual(out, "EN<山田太郎がログイン画面を開く>")  # Echo trả lại [[1]]..[[2]] rồi được khôi phục
        sent, system = fake.calls[0]
        self.assertEqual(sent, "[[1]]が[[2]]を開く")
        self.assertIn("[[1]]", system)
        self.assertTrue(system.startswith("SYS"))
        self.assertEqual(cfg.system_prompt, "SYS")  # cfg gốc không bị đổi

    def test_text_that_is_only_keywords_never_calls_the_model(self):
        cfg, fake = self.cfg(), Echo()
        with patch_translate(fake):
            self.assertEqual(backend.translate_text("山田太郎", cfg), "山田太郎")
        self.assertEqual(fake.calls, [])

    def test_retries_once_when_model_drops_placeholders(self):
        cfg, fake = self.cfg(), Echo(drop_placeholders_times=1)
        with patch_translate(fake):
            out = backend.translate_text("山田太郎が承認する", cfg)
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("山田太郎", out)

    def test_raises_when_model_keeps_dropping_placeholders(self):
        cfg, fake = self.cfg(), Echo(drop_placeholders_times=5)
        with patch_translate(fake):
            with self.assertRaisesRegex(RuntimeError, "từ điển"):
                backend.translate_text("山田太郎が承認する", cfg)
        self.assertEqual(len(fake.calls), 2)

    def test_text_without_any_term_is_sent_as_is_with_original_prompt(self):
        cfg, fake = self.cfg(), Echo()
        with patch_translate(fake):
            backend.translate_text("こんにちは", cfg)
        self.assertEqual(fake.calls[0], ("こんにちは", "SYS"))


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.src = fx.build_fixture(self.dir / "in.xlsx")
        self.out = self.dir / "out.xlsx"

    def run_it(self, terms, cfg=None, fake=None):
        cfg = cfg or default_cfg()
        cfg.dictionary = Dictionary.parse(terms)
        return run_process(self.src, self.out, cfg, fake or Echo())

    def texts(self):
        return sst_texts(read_zip(self.out)[fx.P_SHARED])

    def test_whole_cell_term_is_kept_japanese_and_not_sent_to_model(self):
        (applied, errors), logs, fake = self.run_it("[item]\nりんご\n")
        sent = [c[0] for c in fake.calls]
        self.assertNotIn("りんご", sent)
        self.assertEqual(self.texts()[3], "りんご")
        self.assertEqual(errors, 0)
        self.assertTrue(any("Từ điển: giữ nguyên" in l for l in logs), logs)

    def test_other_cells_are_still_translated(self):
        self.run_it("[item]\nりんご\n")
        self.assertEqual(self.texts()[2], "EN<備考>")

    def test_term_inside_sentence_is_preserved(self):
        self.run_it("[item]\n新鮮\n")
        self.assertEqual(self.texts()[4], "EN<新鮮です>")  # '新鮮' được giữ, phần còn lại do model dịch

    def test_keeping_a_header_keeps_table_name_and_cell_consistent(self):
        self.run_it("[item]\n名前\n")
        parts = read_zip(self.out)
        from xlsx_trans.xlsx_xml import NSMAP, parse

        names = [c.get("name") for c in parse(parts[fx.P_TABLE]).xpath("//m:tableColumn", namespaces=NSMAP)]
        self.assertEqual(names[0], "名前")
        self.assertEqual(self.texts()[0], "名前")

    def test_bilingual_mode_does_not_duplicate_kept_text(self):
        self.run_it("[item]\nりんご\n", cfg=default_cfg(mode="bilingual"))
        self.assertEqual(self.texts()[3], "りんご")

    def test_cache_invalidated_when_dictionary_changes(self):
        self.run_it("[item]\nりんご\n")
        _, _, fake = self.run_it("[item]\nみかん\n")
        self.assertGreater(len(fake.calls), 0)
        _, _, fake2 = self.run_it("[item]\nみかん\n")
        self.assertEqual(fake2.calls, [])

    def test_dictionary_does_not_change_signature_when_empty(self):
        a = default_cfg().signature()
        cfg = default_cfg()
        cfg.dictionary = Dictionary()
        self.assertEqual(a, cfg.signature())

    def test_sheet_name_in_dictionary_gets_no_gloss(self):
        cfg = default_cfg(md=True)
        _, _, fake = self.run_it("[screen]\n売上\n", cfg=cfg)
        self.assertNotIn("売上", [c[0] for c in fake.calls])
        md = self.out.with_suffix(".md").read_text(encoding="utf-8")
        self.assertRegex(md, r"(?m)^## Sheet 1: `売上`$")


class TestConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def load(self, toml):
        (self.dir / "c.toml").write_text(toml, encoding="utf-8")
        return config.load_config(self.dir / "c.toml")

    def test_default_has_empty_dictionary_and_no_warning_when_default_file_missing(self):
        cfg = default_cfg()
        self.assertFalse(cfg.dictionary)
        self.assertEqual(cfg.warnings, [])

    def test_loads_files_relative_to_config(self):
        (self.dir / "d.txt").write_text("[s]\nA画面\n", encoding="utf-8")
        cfg = self.load('[dictionary]\nfiles = ["d.txt"]\n')
        self.assertEqual(cfg.dictionary.terms(), ["A画面"])
        self.assertEqual(cfg.dict_files, [self.dir / "d.txt"])

    def test_declared_but_missing_file_warns(self):
        cfg = self.load('[dictionary]\nfiles = ["none.txt"]\n')
        self.assertTrue(any("từ điển" in w for w in cfg.warnings))

    def test_disabled(self):
        (self.dir / "d.txt").write_text("A\n", encoding="utf-8")
        cfg = self.load('[dictionary]\nenabled = false\nfiles = ["d.txt"]\n')
        self.assertFalse(cfg.dictionary)

    def test_reload_picks_up_edits(self):
        (self.dir / "d.txt").write_text("A\n", encoding="utf-8")
        cfg = self.load('[dictionary]\nfiles = ["d.txt"]\n')
        dictionary.add_term(self.dir / "d.txt", "x", "B")
        cfg.reload_dictionary()
        self.assertEqual(sorted(cfg.dictionary.terms()), ["A", "B"])

    def test_custom_placeholder_note(self):
        cfg = self.load('[dictionary]\nplaceholder_note = "NOTE"\n')
        self.assertEqual(cfg.placeholder_note, "NOTE")


def run_main(*argv):
    with mock.patch("builtins.print") as pr, mock.patch("xlsx_trans.pipeline.process_xlsx") as proc:
        code = cli.main(list(argv))
    return code, pr, proc


class TestCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.cfg_path = self.dir / "c.toml"
        self.cfg_path.write_text('[dictionary]\nfiles = ["d.txt"]\n', encoding="utf-8")

    def test_dict_add_writes_first_file_and_exits(self):
        code, pr, proc = run_main("-c", str(self.cfg_path), "--dict-add", "person", "山田太郎")
        self.assertEqual(code, 0)
        proc.assert_not_called()
        self.assertEqual((self.dir / "d.txt").read_text(encoding="utf-8"), "[person]\n山田太郎\n")
        self.assertIn("Đã thêm", pr.call_args[0][0])
        _, pr2, _ = run_main("-c", str(self.cfg_path), "--dict-add", "person", "山田太郎")
        self.assertIn("Đã có sẵn", pr2.call_args[0][0])

    def test_dict_list(self):
        (self.dir / "d.txt").write_text("[screen]\nA画面\n", encoding="utf-8")
        _, pr, _ = run_main("-c", str(self.cfg_path), "--dict-list")
        printed = [c[0][0] for c in pr.call_args_list]
        self.assertEqual(printed, ["[screen]", "  A画面"])

    def test_dict_option_adds_file_and_no_dict_disables(self):
        extra = self.dir / "extra.txt"
        extra.write_text("[s]\nX画面\n", encoding="utf-8")
        _, _, proc = run_main("in.xlsx", "-c", str(self.cfg_path), "--dict", str(extra))
        self.assertEqual(proc.call_args[0][2].dictionary.terms(), ["X画面"])
        _, _, proc = run_main("in.xlsx", "-c", str(self.cfg_path), "--dict", str(extra), "--no-dict")
        self.assertFalse(proc.call_args[0][2].dictionary)

    def test_invalid_term_is_a_clean_exit(self):
        with self.assertRaises(SystemExit):
            run_main("-c", str(self.cfg_path), "--dict-add", "a", "[x]")


if __name__ == "__main__":
    unittest.main()
