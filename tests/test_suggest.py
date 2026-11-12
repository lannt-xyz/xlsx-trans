"""Gợi ý danh từ riêng chưa có trong từ điển và luồng duyệt/thêm."""
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import fixtures as fx
from tests.fixtures import default_cfg, patch_translate, read_zip, run_process, sst_texts
from xlsx_trans import batch, cli, config, pipeline, suggest
from xlsx_trans.dictionary import Dictionary

RX = re.compile(config.JP_PATTERN)


def terms(cands):
    return {c.term: c.category for c in cands}


class TestDetect(unittest.TestCase):
    def sug(self, texts, dic="", ignored=(), limit=50):
        return suggest.suggest(texts, Dictionary.parse(dic), RX, ignored, limit)

    def test_person_with_honorific(self):
        self.assertEqual(terms(self.sug(["山田太郎さんが承認", "鈴木様へ連絡", "田中氏"])),
                         {"山田太郎": "person", "鈴木": "person", "田中": "person"})

    def test_generic_honorific_words_are_not_names(self):
        self.assertEqual(self.sug(["お客様へ", "ご担当者様", "責任者様", "各位様"]), [])

    def test_screen_names(self):
        got = terms(self.sug(["ログイン画面", "受注一覧", "お客様情報登録"]))
        self.assertEqual(got, {"ログイン画面": "screen", "受注一覧": "screen", "お客様情報登録": "screen"})

    def test_sentences_are_not_screens(self):
        self.assertEqual(self.sug(["注文を確認", "画面を開いて一覧を確認する。", "一覧\n画面"]), [])

    def test_quoted_labels(self):
        self.assertEqual(terms(self.sug(["「保存」ボタンを押す", "【重要】確認", "『受注一覧』を開く"])),
                         {"保存": "label", "重要": "label", "受注一覧": "label"})

    def test_messages_and_katakana(self):
        got = terms(self.sug(["保存しました。", "ステータス", "エラーが発生しました"]))
        self.assertEqual(got["保存しました。"], "message")
        self.assertEqual(got["ステータス"], "item")
        self.assertEqual(got["エラーが発生しました"], "message")

    def test_plain_text_gives_nothing(self):
        self.assertEqual(self.sug(["こんにちは", "本日は晴れです", "ABC-123", "12345"]), [])

    def test_known_ignored_and_covered_terms_are_excluded(self):
        texts = ["ログイン画面", "受注一覧", "山田太郎さん", "ステータス"]
        got = terms(self.sug(texts, dic="[s]\nログイン画面\n", ignored={"受注一覧"}))
        self.assertEqual(got, {"山田太郎": "person", "ステータス": "item"})

    def test_term_fully_covered_by_dictionary_terms_is_excluded(self):
        self.assertEqual(self.sug(["受注一覧"], dic="受注\n一覧\n"), [])

    def test_ordering_priority_then_count_and_limit(self):
        texts = ["ステータス"] * 5 + ["受注一覧"] * 2 + ["顧客詳細"] * 3 + ["山田さん"]
        got = [c.term for c in self.sug(texts)]
        self.assertEqual(got, ["山田", "顧客詳細", "受注一覧", "ステータス"])
        self.assertEqual([c.term for c in self.sug(texts, limit=2)], ["山田", "顧客詳細"])

    def test_counts_and_example(self):
        c = self.sug(["山田太郎さんA", "山田太郎さんB", "山田太郎さん山田太郎さん"])[0]
        self.assertEqual((c.term, c.count), ("山田太郎", 4))
        self.assertEqual(c.example, "山田太郎さんA")

    def test_best_category_wins_for_same_term(self):
        got = terms(self.sug(["受注一覧", "「受注一覧」を開く", "山田さん", "「山田」"]))
        self.assertEqual(got["受注一覧"], "screen")
        self.assertEqual(got["山田"], "person")


class TestIgnoreFile(unittest.TestCase):
    def test_roundtrip_and_comments(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "ign.txt"
            self.assertEqual(suggest.load_ignored(p), set())
            suggest.add_ignored(p, ["A", "B"])
            suggest.add_ignored(p, ["C", " "])
            p.write_text("# ghi chú\n" + p.read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(suggest.load_ignored(p), {"A", "B", "C"})


class TestReviewTexts(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.cfg = default_cfg()
        self.cfg.dict_files = [self.dir / "d.txt"]
        self.cfg.dict_ignore_file = self.dir / "ign.txt"
        self.texts = ["山田太郎さん", "ログイン画面", "ステータス"]

    def run_review(self, decision, **kw):
        seen = []

        def review(cands):
            seen.extend(cands)
            return decision

        logs = []
        n = suggest.review_texts(self.texts, self.cfg, review, logs.append)
        return n, seen, logs

    def test_add_and_ignore_decisions_are_persisted_and_reloaded(self):
        n, seen, logs = self.run_review({"山田太郎": "add", "ステータス": "ignore"})
        self.assertEqual(n, 1)
        self.assertEqual(len(seen), 3)
        self.assertEqual(Dictionary.load([self.dir / "d.txt"]).entries, {"person": ["山田太郎"]})
        self.assertEqual(suggest.load_ignored(self.dir / "ign.txt"), {"ステータス"})
        self.assertEqual(self.cfg.dictionary.terms(), ["山田太郎"])
        self.assertEqual(self.cfg.ignored, {"ステータス"})
        # lần sau chỉ còn lại từ chưa quyết định
        _, seen2, _ = self.run_review({})
        self.assertEqual([c.term for c in seen2], ["ログイン画面"])

    def test_no_decision_changes_nothing(self):
        n, _, _ = self.run_review({})
        self.assertEqual(n, 0)
        self.assertFalse((self.dir / "d.txt").exists())
        self.assertFalse((self.dir / "ign.txt").exists())

    def test_nothing_asked_when_disabled_or_no_review_or_no_candidates(self):
        asked = []
        for cfg_kw in ({"suggest": False}, {"dict_enabled": False}):
            cfg = default_cfg(**cfg_kw)
            suggest.review_texts(self.texts, cfg, lambda c: asked.append(c) or {}, lambda m: None)
        suggest.review_texts(self.texts, self.cfg, None, lambda m: None)
        suggest.review_texts(["こんにちは"], self.cfg, lambda c: asked.append(c) or {}, lambda m: None)
        self.assertEqual(asked, [])


class TestPipelineAndBatch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name).resolve()
        self.cfg = default_cfg()
        self.cfg.dict_files = [self.dir / "d.txt"]
        self.cfg.dict_ignore_file = self.dir / "ign.txt"

    def make_xlsx(self, path, strings):
        import zipfile

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", fx.fixture_parts()["[Content_Types].xml"])
            z.writestr(
                "xl/sharedStrings.xml",
                fx._p(f'<sst xmlns="{fx.MAIN}">' + "".join(f"<si><t>{t}</t></si>" for t in strings) + "</sst>"),
            )
        return path

    def test_accepted_candidate_is_kept_japanese_in_the_same_run(self):
        src = self.make_xlsx(self.dir / "in.xlsx", ["ステータス", "山田太郎さんが承認する"])
        seen = []

        def review(cands):
            seen.extend(c.term for c in cands)
            return {c.term: "add" for c in cands if c.term == "ステータス"}

        fake = fx.FakeTranslator()
        out = self.dir / "out.xlsx"
        with patch_translate(fake):
            pipeline.process_xlsx(src, out, self.cfg, log=lambda m: None, review=review)
        self.assertEqual(seen, ["山田太郎", "ステータス"])
        self.assertNotIn("ステータス", fake.calls)  # đã thêm -> không gửi cho model
        texts = sst_texts(read_zip(out)["xl/sharedStrings.xml"])
        self.assertEqual(texts[0], "ステータス")
        self.assertTrue(texts[1].startswith("EN["))
        self.assertIn("ステータス", (self.dir / "d.txt").read_text(encoding="utf-8"))

    def test_declined_candidate_is_translated_normally(self):
        src = self.make_xlsx(self.dir / "in.xlsx", ["ステータス"])
        fake = fx.FakeTranslator()
        with patch_translate(fake):
            pipeline.process_xlsx(src, self.dir / "o.xlsx", self.cfg, log=lambda m: None, review=lambda c: {})
        self.assertEqual(fake.calls, ["ステータス"])

    def test_review_not_called_without_callback_even_if_candidates_exist(self):
        src = fx.build_fixture(self.dir / "in.xlsx")
        (applied, _), _, fake = run_process(src, self.dir / "o.xlsx", self.cfg)
        self.assertEqual(applied, fx.UNIT_COUNT)

    def test_folder_asks_once_with_counts_aggregated_across_files(self):
        data = fx.make_tree(self.dir / "data")
        calls = []

        def review(cands):
            calls.append(cands)
            return {}

        # chỉ cần gợi ý xuất hiện; thay collect để chắc chắn có ứng viên lặp ở mọi file
        with mock.patch.object(pipeline, "scan_texts", return_value=["山田さん", "受注一覧"]):
            with patch_translate(fx.FakeTranslator()):
                batch.process_folder(data, self.cfg, log=lambda m: None, review=review)
        self.assertEqual(len(calls), 1)
        by = {c.term: c.count for c in calls[0]}
        self.assertEqual(by, {"山田": 6, "受注一覧": 6})

    def test_folder_accepting_updates_dictionary_before_translating(self):
        data = self.dir / "data"
        self.make_xlsx(data / "a.xlsx", ["ステータス", "概要"])
        self.make_xlsx(data / "sub" / "b.xlsx", ["ステータス", "備考"])
        fake = fx.FakeTranslator()
        counts = {}

        def review(cands):
            counts.update({c.term: c.count for c in cands})
            return {c.term: "add" for c in cands}

        with patch_translate(fake):
            batch.process_folder(data, self.cfg, log=lambda m: None, review=review)
        self.assertEqual(counts, {"ステータス": 2})
        self.assertEqual(sorted(fake.calls), ["備考", "概要"])
        out = read_zip(self.dir / "data_en" / "sub" / "b.xlsx")
        self.assertEqual(sst_texts(out["xl/sharedStrings.xml"]), ["ステータス", "EN[備考]"])

    def test_dry_run_never_asks(self):
        data = fx.make_tree(self.dir / "data")
        asked = []
        batch.process_folder(data, self.cfg, log=lambda m: None, dry_run=True, review=lambda c: asked.append(c) or {})
        self.assertEqual(asked, [])


class TestCliReview(unittest.TestCase):
    CANDS = [suggest.Candidate(t, "person", n, "ex") for t, n in (("A山", 3), ("B川", 2), ("C田", 1))]

    def run_review(self, answers, interactive=True):
        out, it = [], iter(answers)
        res = cli.cli_review(self.CANDS, ask=lambda prompt: next(it), out=out.append, interactive=interactive)
        return res, out

    def test_parse_selection(self):
        self.assertEqual(cli.parse_selection("1,3", 3), {1, 3})
        self.assertEqual(cli.parse_selection("2-3", 3), {2, 3})
        self.assertEqual(cli.parse_selection("3-1", 3), {1, 2, 3})
        self.assertEqual(cli.parse_selection(" a ", 3), {1, 2, 3})
        self.assertEqual(cli.parse_selection("", 3), set())
        self.assertEqual(cli.parse_selection("9, 2", 3), {2})
        with self.assertRaises(ValueError):
            cli.parse_selection("x", 3)

    def test_select_some_and_keep_asking_later(self):
        res, out = self.run_review(["1,3", "n"])
        self.assertEqual(res, {"A山": "add", "C田": "add"})
        self.assertTrue(any("A山" in l for l in out))

    def test_never_ask_again_for_rest(self):
        res, _ = self.run_review(["2", "y"])
        self.assertEqual(res, {"B川": "add", "A山": "ignore", "C田": "ignore"})

    def test_all_needs_no_second_question(self):
        res, _ = self.run_review(["a"])
        self.assertEqual(set(res.values()), {"add"})
        self.assertEqual(len(res), 3)

    def test_enter_skips_and_invalid_input_reprompts(self):
        res, out = self.run_review(["zzz", "", "n"])
        self.assertEqual(res, {})
        self.assertTrue(any("Không hiểu" in l for l in out))

    def test_non_interactive_skips_without_asking(self):
        res, out = self.run_review([], interactive=False)
        self.assertEqual(res, {})
        self.assertTrue(any("không có terminal" in l for l in out))

    def test_cli_passes_review_and_no_suggest_flag(self):
        with mock.patch.object(pipeline, "process_xlsx") as proc:
            cli.main(["in.xlsx"])
            self.assertIs(proc.call_args[1]["review"], cli.cli_review)
            self.assertTrue(proc.call_args[0][2].suggest)
            cli.main(["in.xlsx", "--no-suggest"])
            self.assertFalse(proc.call_args[0][2].suggest)


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = default_cfg()
        self.assertTrue(cfg.suggest)
        self.assertEqual(cfg.suggest_max, 50)
        self.assertTrue(str(cfg.dict_files[0]).endswith("resources/dictionary.txt"))
        self.assertTrue(str(cfg.dict_ignore_file).endswith("resources/dictionary.ignore.txt"))

    def test_shipped_config_points_to_resources(self):
        cfg = config.load_config()
        self.assertEqual(cfg.dict_files[0], config.APP_DIR / "resources" / "dictionary.txt")
        self.assertTrue(cfg.dict_files[0].is_file())
        self.assertEqual(cfg.warnings, [])


if __name__ == "__main__":
    unittest.main()
