"""Dịch thủ công qua chat: chia khối, nhập kết quả, tạo file từ cache."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import fixtures as fx
from tests.fixtures import default_cfg, read_zip, sst_texts
from xlsx_trans import cli, config, manual, pipeline, tokens
from xlsx_trans.dictionary import Dictionary


def count_len(text):
    return len(text)


def reply_for(block, fmt=lambda it: f"EN[{it.masked}]"):
    return "\n".join(f"[{it.id}] {fmt(it)}" for it in block.items)


class TestTokens(unittest.TestCase):
    def test_estimate_is_conservative_for_japanese(self):
        self.assertGreaterEqual(tokens.estimate("ログイン画面"), 6)
        self.assertLess(tokens.estimate("hello world"), 6)

    def test_counter_falls_back_when_tiktoken_unavailable(self):
        c = tokens.TokenCounter("o200k_base")
        self.assertGreater(c("日本語のテキスト"), 0)
        self.assertIn(c.kind, ("estimate",) + (("tiktoken:o200k_base",) if c._enc else ()))

    def test_estimate_name_never_loads_tiktoken(self):
        self.assertEqual(tokens.TokenCounter("estimate").kind, "estimate")


class TestFormat(unittest.TestCase):
    def test_newline_roundtrip(self):
        self.assertEqual(manual.encode_item("a\r\nb\nc"), "a<br>b<br>c")
        self.assertEqual(manual.decode_item("a<br>b<BR/>c<br />d"), "a\nb\nc\nd")

    def test_parse_output_plain_fences_and_wrapping(self):
        text = "```\n[1] Hello\n[2] Long line that\n  the chat wrapped\n\n[3]   Third\n```\nnoise before? no"
        got = manual.parse_output(text)
        self.assertEqual(got[1], "Hello")
        self.assertEqual(got[2], "Long line that the chat wrapped")
        self.assertEqual(got[3], "Third noise before? no")  # dòng thừa sau mục cuối bị nối vào mục đó

    def test_parse_ignores_leading_noise_and_placeholders(self):
        got = manual.parse_output("Here you go:\n[1] [[1]] opens\n[[2]] is not an item\n[2] Two")
        self.assertEqual(got, {1: "[[1]] opens [[2]] is not an item", 2: "Two"})


class SessionCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name).resolve()
        self.cfg = default_cfg(system_prompt="SYS")
        self.src = fx.build_fixture(self.dir / "in.xlsx")

    def session(self, path=None, **kw):
        return manual.ManualSession(self.cfg, path or self.src, counter=count_len, **kw)


class TestBlocks(SessionCase):
    def test_scan_collects_unique_strings_in_order(self):
        s = self.session()
        blocks = s.scan()
        items = [it for b in blocks for it in b.items]
        self.assertEqual(len(items), fx.UNIQUE_COUNT)
        self.assertEqual(s.total, fx.UNIQUE_COUNT)
        self.assertEqual(len({it.text for it in items}), fx.UNIQUE_COUNT)

    def test_prompt_has_system_prompt_rules_and_numbered_items(self):
        b = self.session().scan()[0]
        self.assertTrue(b.prompt.startswith("SYS\n\n"))
        self.assertIn("ITEMS:\n[1] ", b.prompt)
        self.assertIn(self.cfg.manual_instruction.strip().splitlines()[0], b.prompt)
        self.assertEqual(b.tokens, len(b.prompt))

    def test_blocks_respect_token_budget_and_renumber(self):
        budget = len(manual.render_prompt(self.cfg, [])) + 80
        self.cfg.block_tokens = budget
        blocks = self.session().scan()
        self.assertGreater(len(blocks), 1)
        for b in blocks:
            self.assertLessEqual(b.tokens, budget)
            self.assertEqual([i.id for i in b.items], list(range(1, len(b.items) + 1)))
        self.assertEqual(sum(len(b.items) for b in blocks), fx.UNIQUE_COUNT)

    def test_max_items_per_block(self):
        self.cfg.block_max_items = 4
        blocks = self.session().scan()
        self.assertTrue(all(len(b.items) <= 4 for b in blocks))
        self.assertEqual(len(blocks), -(-fx.UNIQUE_COUNT // 4))

    def test_item_bigger_than_budget_gets_its_own_block(self):
        items = [manual.Item(0, "x" * 50, "x" * 50), manual.Item(0, "y", "y")]
        self.cfg.block_tokens = 300
        blocks = manual.make_blocks(items, self.cfg, lambda t: len(t) * 10)
        self.assertEqual([len(b.items) for b in blocks], [1, 1])

    def test_multiline_cell_is_encoded_with_br(self):
        b = self.session().scan()
        text = "\n".join(bl.prompt for bl in b)
        self.assertIn("1行目<br>2行目", text)
        self.assertNotIn("1行目\n2行目", text)

    def test_cached_strings_are_skipped_and_progress_counts(self):
        s = self.session()
        blocks = s.scan()
        first = len(blocks[0].items)
        s.apply_output(blocks[0], reply_for(blocks[0]))
        s2 = self.session()
        s2.scan()
        self.assertEqual(sum(len(b.items) for b in s2.blocks), fx.UNIQUE_COUNT - first)
        self.assertEqual(s2.done_count(), first)

    def test_dictionary_terms_are_masked_and_whole_term_cells_skipped(self):
        self.cfg.dictionary = Dictionary.parse("[item]\nりんご\n[x]\n新鮮\n")
        s = self.session()
        s.scan()
        items = {it.text: it for b in s.blocks for it in b.items}
        self.assertNotIn("りんご", items)  # chỉ gồm từ khóa -> không cần dịch
        self.assertEqual(items["新鮮です"].masked, "[[1]]です")
        self.assertEqual(items["新鮮です"].mapping, {1: "新鮮"})


class TestApply(SessionCase):
    def test_all_saved_and_cache_written_to_disk(self):
        s = self.session()
        block = s.scan()[0]
        n = len(block.items)
        res = s.apply_output(block, reply_for(block))
        self.assertEqual((len(res.saved), res.missing, res.bad, res.extra), (n, [], [], 0))
        self.assertEqual(block.items, [])
        self.assertTrue(s.cache_path().exists())
        data = json.loads(s.cache_path().read_text(encoding="utf-8"))
        self.assertEqual(len(data["map"]), n)
        self.assertEqual(data["map"]["りんご"], "EN[りんご]")

    def test_br_in_reply_becomes_newline(self):
        s = self.session()
        block = s.scan()[0]
        s.apply_output(block, reply_for(block, lambda it: "EN: " + manual.encode_item(it.text)))
        self.assertEqual(s.cache.get("1行目\n2行目"), "EN: 1行目\n2行目")

    def test_missing_items_are_reported_and_retry_block_has_only_them(self):
        s = self.session()
        block = s.scan()[0]
        lines = reply_for(block).splitlines()
        lines.pop(1)
        lines.pop(3)
        res = s.apply_output(block, "\n".join(lines))
        self.assertEqual(len(res.missing), 2)
        retry = s.retry_block(block, res)
        self.assertEqual(len(retry), 1)
        self.assertEqual(len(retry[0].items), 2)
        self.assertEqual([i.id for i in retry[0].items], [1, 2])
        res2 = s.apply_output(retry[0], reply_for(retry[0]))
        self.assertEqual(len(res2.saved), 2)
        self.assertEqual(s.done_count(), fx.UNIQUE_COUNT)

    def test_empty_translation_counts_as_missing(self):
        s = self.session()
        block = s.scan()[0]
        res = s.apply_output(block, "[1] \n" + "\n".join(reply_for(block).splitlines()[1:]))
        self.assertEqual(res.missing, [1])

    def test_extra_numbers_are_counted_and_ignored(self):
        s = self.session()
        block = s.scan()[0]
        res = s.apply_output(block, reply_for(block) + "\n[999] stray")
        self.assertEqual(res.extra, 1)
        self.assertNotIn("stray", s.cache.map.values())

    def test_untranslated_japanese_is_saved_but_flagged(self):
        s = self.session()
        block = s.scan()[0]
        res = s.apply_output(block, reply_for(block, lambda it: it.text))
        self.assertTrue(res.suspect)
        self.assertIn("名前", s.cache.map)  # vẫn được lưu dù bị đánh dấu nghi ngờ
        self.assertEqual(res.missing + [b for b, _ in res.bad], [])

    def test_placeholders_are_restored_and_missing_ones_rejected(self):
        self.cfg.dictionary = Dictionary.parse("[x]\n新鮮\n")
        s = self.session()
        block = next(b for b in s.scan() if any(i.mapping for i in b.items))
        target = next(i for i in block.items if i.mapping)
        good = reply_for(block, lambda it: f"Very {it.masked}")
        res = s.apply_output(block, good)
        self.assertEqual(s.cache.get(target.text), "Very 新鮮です")  # "[[1]]です" -> "新鮮です"
        self.assertEqual(res.bad, [])

        s.cache_path().unlink()
        s2 = self.session()
        blocks2 = s2.scan()
        block2 = next(b for b in blocks2 if any(i.mapping for i in b.items))
        bad = reply_for(block2, lambda it: "No placeholder here")
        res2 = s2.apply_output(block2, bad)
        self.assertEqual(len(res2.bad), 1)
        self.assertIn("ký hiệu", res2.bad[0][1])
        self.assertNotIn(target.text, s2.cache.map)
        self.assertEqual(s2.retry_block(block2, res2)[0].items[0].text, target.text)


class TestFinish(SessionCase):
    def translate_all(self, s):
        for b in list(s.blocks):
            s.apply_output(b, reply_for(b))

    def test_file_output_from_cache_without_model(self):
        s = self.session()
        s.scan()
        self.translate_all(s)
        out = pipeline.default_out(self.src, self.cfg)
        with mock.patch("xlsx_trans.ollama.translate_text", side_effect=AssertionError("không được gọi model")):
            applied, errors = s.finish(log=lambda m: None)
        self.assertEqual((applied, errors), (fx.UNIT_COUNT, 0))
        parts = read_zip(out)
        self.assertEqual(sst_texts(parts[fx.P_SHARED])[0], "EN[名前]")

    def test_unfinished_strings_stay_japanese_and_are_reported(self):
        s = self.session()
        blocks = s.scan()
        block = blocks[0]
        lines = reply_for(block).splitlines()
        s.apply_output(block, "\n".join(lines[:5]))
        logs = []
        applied, errors = s.finish(log=logs.append)
        self.assertGreater(errors, 0)
        self.assertTrue(any("thủ công" in l for l in logs), logs)
        texts = sst_texts(read_zip(pipeline.default_out(self.src, self.cfg))[fx.P_SHARED])
        self.assertEqual(texts[0], "EN[名前]")
        self.assertIn("合計", texts)

    def test_session_does_not_change_callers_config(self):
        self.session().scan()
        self.assertEqual(self.cfg.backend, "ollama")
        self.assertEqual(self.cfg.model, default_cfg().model)

    def test_manual_backend_has_its_own_cache_signature(self):
        c = default_cfg()
        m = default_cfg(backend="manual")
        m.refresh()
        self.assertNotEqual(c.signature(), m.signature())
        self.assertEqual(m.model, "manual")

    def test_folder_mode_shares_cache_and_mirrors_structure(self):
        data = fx.make_tree(self.dir / "data")
        s = manual.ManualSession(self.cfg, data, counter=count_len)
        blocks = s.scan()
        self.assertEqual(sum(len(b.items) for b in blocks), fx.UNIQUE_COUNT)  # 6 file giống nhau -> gộp
        for b in list(s.blocks):
            s.apply_output(b, reply_for(b))
        self.assertEqual(s.cache_path(), self.dir / "data_en.cache.json")
        res = s.finish(log=lambda m: None)
        self.assertEqual(len(res.ok), 6)
        self.assertEqual(res.errors, 0)
        self.assertTrue((self.dir / "data_en" / "sub" / "deep" / "er" / "d.xlsx").exists())


class TestFiles(SessionCase):
    def test_export_import_roundtrip_with_retry_files(self):
        self.cfg.block_max_items = 5
        out = self.dir / "blocks"
        s = self.session()
        n = manual.export_blocks(s, out)
        self.assertEqual(n, 3)
        self.assertTrue((out / "block-001.txt").read_text(encoding="utf-8").startswith("SYS"))
        meta = json.loads((out / "block-001.json").read_text(encoding="utf-8"))
        self.assertEqual([m["id"] for m in meta], [1, 2, 3, 4, 5])

        # trả lời block 1 đủ, block 2 thiếu mục 2, block 3 chưa trả lời
        b1 = (out / "block-001.txt").read_text(encoding="utf-8")
        for k, drop in ((1, None), (2, 2)):
            items = json.loads((out / f"block-00{k}.json").read_text(encoding="utf-8"))
            lines = [f"[{m['id']}] EN[{m['masked']}]" for m in items if m["id"] != drop]
            (out / f"block-00{k}.out.txt").write_text("\n".join(lines), encoding="utf-8")
        s2 = self.session()
        logs = []
        saved, redo = manual.import_blocks(s2, out, logs.append)
        self.assertEqual((saved, redo), (9, 1))
        self.assertTrue((out / "block-002-retry1.txt").exists())
        retry_meta = json.loads((out / "block-002-retry1.json").read_text(encoding="utf-8"))
        self.assertEqual(len(retry_meta), 1)
        self.assertTrue(any("thiếu [2]" in l for l in logs))

    def test_cli_export_then_import_creates_files(self):
        out = self.dir / "blocks"
        cfg_path = self.dir / "c.toml"
        cfg_path.write_text("", encoding="utf-8")
        with mock.patch("builtins.print"):
            self.assertEqual(cli.main([str(self.src), "-c", str(cfg_path), "--manual-export", str(out)]), 0)
        for txt in sorted(out.glob("block-*.json")):
            items = json.loads(txt.read_text(encoding="utf-8"))
            txt.with_name(txt.stem + ".out.txt").write_text(
                "\n".join(f"[{m['id']}] EN[{m['masked']}]" for m in items), encoding="utf-8"
            )
        with mock.patch("builtins.print"):
            code = cli.main([str(self.src), "-c", str(cfg_path), "--manual-import", str(out)])
        self.assertEqual(code, 0)
        parts = read_zip(self.dir / "in_en.xlsx")
        self.assertEqual(sst_texts(parts[fx.P_SHARED])[0], "EN[名前]")


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = default_cfg()
        self.assertEqual((cfg.manual_tokenizer, cfg.block_tokens, cfg.block_max_items), ("o200k_base", 6000, 300))
        self.assertIn("ITEMS", cfg.manual_instruction)

    def test_invalid_budget(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text("[manual]\nblock_tokens = 10\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                config.load_config(p)

    def test_shipped_instruction_file_matches_default(self):
        self.assertEqual(config.load_config().manual_instruction.split(), config.DEFAULT_MANUAL_INSTRUCTION.split())


if __name__ == "__main__":
    unittest.main()
