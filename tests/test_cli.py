import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import default_cfg
from xlsx_trans import batch, cli, config, gui, pipeline


def run_main(*argv, folder_result=None):
    """Chạy cli.main(argv) với process_xlsx / process_folder / run_gui bị thay bằng mock."""
    res = folder_result or batch.BatchResult(None)
    with mock.patch.object(pipeline, "process_xlsx") as proc, \
            mock.patch.object(batch, "process_folder", return_value=res) as folder, \
            mock.patch.object(gui, "run_gui") as g:
        code = cli.main(list(argv))
    return code, proc, folder, g


def write_toml(d, text, name="my.toml"):
    p = Path(d) / name
    p.write_text(text, encoding="utf-8")
    return str(p)


class TestFileMode(unittest.TestCase):
    def test_no_arguments_opens_gui_with_loaded_config(self):
        code, proc, folder, g = run_main()
        self.assertEqual(code, 0)
        proc.assert_not_called()
        folder.assert_not_called()
        g.assert_called_once()
        self.assertEqual(g.call_args[0][0].model, config.load_config().model)

    def test_input_only_uses_config_values_and_default_output(self):
        code, proc, folder, g = run_main("data/report.xlsx")
        g.assert_not_called()
        folder.assert_not_called()
        in_path, out_path, cfg = proc.call_args[0]
        self.assertEqual(str(in_path), str(Path("data/report.xlsx")))
        self.assertEqual(out_path, pipeline.default_out(Path("data/report.xlsx"), cfg))
        self.assertIsNone(proc.call_args[1]["md_path"])

    def test_command_line_overrides_config(self):
        _, proc, _, _ = run_main(
            "in.xlsx", "-o", "res.xlsx", "-m", "gemma2:2b", "--host", "http://h:9/",
            "--mode", "bilingual", "--no-md", "--md-out", "x.md",
        )
        _, out_path, cfg = proc.call_args[0]
        self.assertEqual(out_path, "res.xlsx")
        self.assertEqual((cfg.model, cfg.host, cfg.mode, cfg.md), ("gemma2:2b", "http://h:9", "bilingual", False))
        self.assertEqual(proc.call_args[1]["md_path"], "x.md")

    def test_config_option_loads_given_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_toml(d, '[ollama]\nmodel = "from-file"\n[output]\nsuffix = "_vi"\n')
            _, proc, _, _ = run_main("in.xlsx", "-c", p)
        _, out_path, cfg = proc.call_args[0]
        self.assertEqual(cfg.model, "from-file")
        self.assertEqual(out_path, "in_vi.xlsx")

    def test_cli_override_beats_config_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_toml(d, '[ollama]\nmodel = "from-file"\n')
            _, proc, _, _ = run_main("in.xlsx", "-c", p, "-m", "from-cli")
        self.assertEqual(proc.call_args[0][2].model, "from-cli")

    def test_config_with_gui_when_no_input(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_toml(d, '[ollama]\nmodel = "from-file"\n')
            _, _, _, g = run_main("-c", p)
        self.assertEqual(g.call_args[0][0].model, "from-file")

    def test_missing_or_invalid_config_exits_with_message(self):
        with self.assertRaises(SystemExit) as cm:
            run_main("in.xlsx", "-c", "/không/tồn/tại.toml")
        self.assertIn("Lỗi cấu hình", str(cm.exception.code))
        with tempfile.TemporaryDirectory() as d:
            p = write_toml(d, '[translate]\nmode = "x"\n', "bad.toml")
            with self.assertRaises(SystemExit) as cm:
                run_main("in.xlsx", "-c", p)
        self.assertIn("Lỗi cấu hình", str(cm.exception.code))

    def test_invalid_mode_is_rejected_by_argparse(self):
        with self.assertRaises(SystemExit) as cm, mock.patch("sys.stderr"):
            run_main("in.xlsx", "--mode", "nope")
        self.assertEqual(cm.exception.code, 2)

    def test_processing_errors_become_clean_exit(self):
        for exc in (OSError("khóa"), ValueError("sai"), __import__("zipfile").BadZipFile("hỏng")):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(pipeline, "process_xlsx", side_effect=exc):
                    with self.assertRaises(SystemExit) as cm:
                        cli.main(["in.xlsx"])
                self.assertTrue(str(cm.exception.code).startswith("Lỗi: "))

    def test_dry_run_on_file_prints_plan_only(self):
        with mock.patch("builtins.print") as pr:
            code, proc, _, _ = run_main("in.xlsx", "--dry-run")
        self.assertEqual(code, 0)
        proc.assert_not_called()
        self.assertIn("in_en.xlsx", pr.call_args[0][0])


class TestFolderMode(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_directory_goes_to_process_folder(self):
        code, proc, folder, _ = run_main(str(self.dir))
        self.assertEqual(code, 0)
        proc.assert_not_called()
        self.assertEqual(Path(folder.call_args[0][0]), self.dir)
        self.assertIsNone(folder.call_args[1]["out_dir"])
        self.assertIsNone(folder.call_args[1]["md_dir"])
        self.assertFalse(folder.call_args[1]["dry_run"])

    def test_folder_options_are_passed_through(self):
        _, _, folder, _ = run_main(
            str(self.dir), "-o", "outd", "--md-out", "mdd", "--dry-run", "--no-recursive"
        )
        kw = folder.call_args[1]
        self.assertEqual((kw["out_dir"], kw["md_dir"], kw["dry_run"]), ("outd", "mdd", True))
        self.assertFalse(folder.call_args[0][1].recursive)

    def test_recursive_by_default(self):
        _, _, folder, _ = run_main(str(self.dir))
        self.assertTrue(folder.call_args[0][1].recursive)

    def test_exit_code_is_1_when_any_file_failed(self):
        res = batch.BatchResult(None, failed=[(Path("a.xlsx"), "lỗi")])
        code, *_ = run_main(str(self.dir), folder_result=res)
        self.assertEqual(code, 1)

    def test_value_error_from_batch_is_a_clean_exit(self):
        with mock.patch.object(batch, "process_folder", side_effect=ValueError("trong input")):
            with self.assertRaises(SystemExit) as cm:
                cli.main([str(self.dir)])
        self.assertIn("trong input", str(cm.exception.code))


class TestParser(unittest.TestCase):
    def test_input_is_optional(self):
        a = cli.build_parser().parse_args([])
        self.assertIsNone(a.input)


if __name__ == "__main__":
    unittest.main()
