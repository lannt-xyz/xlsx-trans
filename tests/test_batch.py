"""Test dịch cả folder: kế hoạch, cấu trúc output, cache chung, lỗi, dừng giữa chừng."""
import json
import tempfile
import unittest
from pathlib import Path

from tests import fixtures as fx
from tests.fixtures import FakeTranslator, default_cfg, files_under, patch_translate, read_zip, sst_texts
from xlsx_trans import batch

try:
    import openpyxl  # noqa: F401
    HAVE_OPENPYXL = True
except ImportError:  # pragma: no cover
    HAVE_OPENPYXL = False

EXPECTED_SST_B = "EN[名前]"


class BatchTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.data = fx.make_tree(self.base / "data")
        self.cfg = default_cfg()

    def run_folder(self, cfg=None, fake=None, **kw):
        fake = fake or FakeTranslator()
        logs = []
        with patch_translate(fake):
            res = batch.process_folder(self.data, cfg or self.cfg, log=logs.append, **kw)
        return res, logs, fake


class TestDeriveAndPlan(BatchTestCase):
    def test_derive_dirs_uses_suffixes(self):
        cfg = default_cfg(md=True)
        out, md = batch.derive_dirs(self.data, cfg)
        self.assertEqual((out.name, md.name), ("data_en", "data_en_md"))
        self.assertEqual(out.parent, self.data.parent)

    def test_derive_dirs_custom_suffixes_and_md_disabled(self):
        out, md = batch.derive_dirs(self.data, default_cfg(suffix="_vi", md_suffix="_docs", md=True))
        self.assertEqual((out.name, md.name), ("data_vi", "data_vi_docs"))
        out, md = batch.derive_dirs(self.data, default_cfg(md=False))
        self.assertIsNone(md)

    def test_derive_dirs_rejects_root(self):
        with self.assertRaises(ValueError):
            batch.derive_dirs(Path("/"), self.cfg)

    def test_plan_lists_valid_files_only(self):
        plan = batch.plan_folder(self.data, default_cfg(md=True))
        self.assertEqual({j.rel.as_posix() for j in plan.jobs}, fx.VALID_FILES)
        self.assertEqual([r.as_posix() for r in plan.unsupported], ["old.xls"])

    def test_plan_mirrors_structure_and_names(self):
        plan = batch.plan_folder(self.data, default_cfg(md=True))
        by = {j.rel.as_posix(): j for j in plan.jobs}
        self.assertEqual(plan.out_dir, self.base / "data_en")
        self.assertEqual(plan.md_dir, self.base / "data_en_md")
        self.assertEqual(by["sub/deep/er/d.xlsx"].out, self.base / "data_en/sub/deep/er/d.xlsx")
        self.assertEqual(by["sub/c.xlsx"].md, self.base / "data_en_md/sub/c.md")
        self.assertEqual(by["a.xlsx"].md, self.base / "data_en_md/a.md")
        self.assertEqual(by["b.xlsm"].out.name, "b.xlsm")

    def test_md_none_when_disabled(self):
        plan = batch.plan_folder(self.data, default_cfg(md=False))
        self.assertIsNone(plan.md_dir)
        self.assertTrue(all(j.md is None for j in plan.jobs))

    def test_md_name_collision_keeps_original_extension(self):
        plan = batch.plan_folder(self.data, default_cfg(md=True))
        by = {j.rel.as_posix(): j for j in plan.jobs}
        self.assertEqual(by["sub/x.xlsx"].md.name, "x.xlsx.md")
        self.assertEqual(by["sub/x.xlsm"].md.name, "x.xlsm.md")
        mds = [j.md for j in plan.jobs]
        self.assertEqual(len(mds), len(set(mds)))

    def test_non_recursive_only_top_level(self):
        plan = batch.plan_folder(self.data, default_cfg(recursive=False))
        self.assertEqual({j.rel.as_posix() for j in plan.jobs}, {"a.xlsx", "b.xlsm"})

    def test_explicit_dirs_override_defaults(self):
        plan = batch.plan_folder(self.data, default_cfg(md=True), self.base / "o", self.base / "m")
        self.assertEqual((plan.out_dir, plan.md_dir), (self.base / "o", self.base / "m"))

    def test_jobs_are_sorted_deterministically(self):
        rels = [j.rel.as_posix() for j in batch.plan_folder(self.data, self.cfg).jobs]
        self.assertEqual(rels, sorted(rels, key=lambda r: [p.casefold() for p in r.split("/")]))

    def test_validation_errors(self):
        with self.assertRaisesRegex(ValueError, "thư mục"):
            batch.plan_folder(self.data / "a.xlsx", self.cfg)
        with self.assertRaisesRegex(ValueError, "nằm trong"):
            batch.plan_folder(self.data, self.cfg, out_dir=self.data / "out")
        with self.assertRaisesRegex(ValueError, "nằm trong"):
            batch.plan_folder(self.data, default_cfg(md=True), md_dir=self.data / "md")
        with self.assertRaisesRegex(ValueError, "khác"):
            batch.plan_folder(self.data, default_cfg(md=True), self.base / "same", self.base / "same")

    def test_planning_writes_nothing(self):
        before = files_under(self.base)
        batch.plan_folder(self.data, default_cfg(md=True))
        self.assertEqual(files_under(self.base), before)
        self.assertFalse((self.base / "data_en").exists())


class TestProcessFolder(BatchTestCase):
    def test_output_mirrors_input_structure(self):
        res, _, _ = self.run_folder()
        self.assertEqual(files_under(self.base / "data_en"), fx.VALID_FILES)
        self.assertEqual(len(res.ok), 6)
        self.assertEqual((res.failed, res.interrupted, res.stopped), ([], [], False))

    def test_files_are_translated(self):
        self.run_folder()
        for rel in fx.VALID_FILES:
            parts = read_zip(self.base / "data_en" / rel)
            self.assertEqual(sst_texts(parts[fx.P_SHARED])[0], EXPECTED_SST_B, rel)

    def test_inputs_are_untouched_and_nothing_created_inside_input(self):
        before = {r: (self.data / r).read_bytes() for r in files_under(self.data)}
        self.run_folder()
        self.assertEqual({r: (self.data / r).read_bytes() for r in files_under(self.data)}, before)

    def test_totals(self):
        res, _, _ = self.run_folder()
        self.assertEqual((res.applied, res.errors), (6 * fx.UNIT_COUNT, 0))

    def test_shared_cache_translates_each_unique_string_once_across_files(self):
        _, logs, fake = self.run_folder()
        self.assertEqual(len(fake.calls), fx.UNIQUE_COUNT)
        self.assertEqual(len(set(fake.calls)), fx.UNIQUE_COUNT)

    def test_cache_file_is_sibling_of_output_not_inside(self):
        self.run_folder()
        cache = self.base / "data_en.cache.json"
        self.assertTrue(cache.exists())
        self.assertEqual(len(json.loads(cache.read_text(encoding="utf-8"))["map"]), fx.UNIQUE_COUNT)
        self.assertFalse(any(p.endswith(".cache.json") for p in files_under(self.base / "data_en")))

    def test_second_run_makes_no_model_calls(self):
        self.run_folder()
        _, _, fake = self.run_folder()
        self.assertEqual(fake.calls, [])

    def test_progress_callbacks(self):
        seen = []
        self.run_folder(file_progress=lambda d, t, rel: seen.append((d, t, rel.as_posix())))
        self.assertEqual(seen[0][:2], (0, 6))
        self.assertEqual(seen[-1][:2], (6, 6))
        self.assertEqual(sorted({s[2] for s in seen}), sorted(fx.VALID_FILES))

    def test_empty_folder(self):
        (self.base / "emptyd").mkdir()
        logs = []
        res = batch.process_folder(self.base / "emptyd", self.cfg, log=logs.append)
        self.assertEqual(res.ok, [])
        self.assertTrue(any("Không có file nào" in l for l in logs))
        self.assertFalse((self.base / "emptyd_en").exists())

    def test_dry_run_writes_nothing_and_lists_plan(self):
        before = files_under(self.base)
        res, logs, fake = self.run_folder(dry_run=True)
        self.assertEqual(fake.calls, [])
        self.assertEqual(files_under(self.base), before)
        self.assertTrue(any("sub" in l and "->" in l for l in logs))
        self.assertTrue(any("old.xls" in l for l in logs))
        self.assertEqual(res.ok, [])

    def test_unrelated_file_in_output_dir_is_preserved(self):
        keep = self.base / "data_en" / "keep.txt"
        keep.parent.mkdir()
        keep.write_text("giữ")
        self.run_folder()
        self.assertEqual(keep.read_text(), "giữ")

    def test_non_excel_files_are_not_copied(self):
        self.run_folder()
        self.assertFalse(any(p.endswith((".txt", ".xls")) for p in files_under(self.base / "data_en")))

    def test_changing_prompt_invalidates_shared_cache(self):
        self.run_folder()
        _, _, fake = self.run_folder(cfg=default_cfg(system_prompt="khác"))
        self.assertEqual(len(fake.calls), fx.UNIQUE_COUNT)

    def test_explicit_output_dirs(self):
        self.run_folder(out_dir=self.base / "X", md_dir=None)
        self.assertEqual(files_under(self.base / "X"), fx.VALID_FILES)
        self.assertTrue((self.base / "X.cache.json").exists())
        self.assertFalse((self.base / "data_en").exists())


@unittest.skipUnless(HAVE_OPENPYXL, "cần openpyxl")
class TestMarkdownFolder(BatchTestCase):
    def test_markdown_tree_is_created(self):
        cfg = default_cfg(md=True)
        self.run_folder(cfg=cfg)
        md_files = files_under(self.base / "data_en_md")
        self.assertEqual(
            md_files,
            {"a.md", "b.md", "sub/c.md", "sub/x.xlsx.md", "sub/x.xlsm.md", "sub/deep/er/d.md"},
        )
        text = (self.base / "data_en_md/sub/deep/er/d.md").read_text(encoding="utf-8")
        self.assertIn("| # | A | B | C | D |", text)

    def test_gloss_adds_one_call_total(self):
        _, _, fake = self.run_folder(cfg=default_cfg(md=True))
        self.assertEqual(len(fake.calls), fx.UNIQUE_COUNT + 1)


class TestErrorsAndStop(BatchTestCase):
    def corrupt(self):
        (self.data / "b.xlsm").write_bytes(b"khong phai zip")

    def test_continue_on_error_processes_the_rest(self):
        self.corrupt()
        res, logs, _ = self.run_folder()
        self.assertEqual([r.as_posix() for r, _ in res.failed], ["b.xlsm"])
        self.assertEqual(len(res.ok), 5)
        self.assertEqual(files_under(self.base / "data_en"), fx.VALID_FILES - {"b.xlsm"})
        self.assertTrue(any("LỖI" in l for l in logs))

    def test_stop_on_first_error_when_configured(self):
        self.corrupt()
        res, logs, _ = self.run_folder(cfg=default_cfg(continue_on_error=False))
        self.assertEqual(len(res.failed), 1)
        self.assertEqual([r.as_posix() for r in res.ok], ["a.xlsx"])  # a < b theo thứ tự quét
        self.assertTrue(any("continue_on_error" in l for l in logs))

    def test_stop_before_next_file(self):
        count = {"n": 0}

        def file_progress(done, total, rel):
            count["n"] = done

        res, logs, _ = self.run_folder(file_progress=file_progress, should_stop=lambda: count["n"] >= 2)
        self.assertTrue(res.stopped)
        self.assertEqual(len(res.ok), 2)
        self.assertEqual(res.interrupted, [])
        self.assertEqual(len(files_under(self.base / "data_en")), 2)

    def test_stop_during_file_marks_it_interrupted_and_resume_finishes(self):
        fake1 = FakeTranslator()
        res, _, _ = self.run_folder(fake=fake1, should_stop=lambda: len(fake1.calls) >= 3)
        self.assertTrue(res.stopped)
        self.assertEqual([r.as_posix() for r in res.interrupted], ["a.xlsx"])
        self.assertEqual(res.ok, [])

        res2, _, fake2 = self.run_folder()
        self.assertEqual(len(res2.ok), 6)
        self.assertEqual(len(fake1.calls) + len(fake2.calls), fx.UNIQUE_COUNT)
        parts = read_zip(self.base / "data_en/a.xlsx")
        self.assertEqual(sst_texts(parts[fx.P_SHARED])[3], "EN[りんご]")

    def test_translation_errors_are_counted_not_fatal(self):
        res, _, _ = self.run_folder(fake=FakeTranslator(fail_on={"りんご"}))
        self.assertEqual(len(res.ok), 6)
        self.assertEqual(res.errors, 6)


if __name__ == "__main__":
    unittest.main()
