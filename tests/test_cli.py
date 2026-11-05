import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import default_cfg
import app


def run_main(*argv):
    """Chạy app.main() với argv giả, process_xlsx / run_gui bị thay bằng mock."""
    with mock.patch.object(sys, "argv", ["app.py", *argv]), \
            mock.patch.object(app, "process_xlsx") as proc, \
            mock.patch.object(app, "run_gui") as gui:
        app.main()
    return proc, gui


class TestMain(unittest.TestCase):
    def test_no_arguments_opens_gui_with_loaded_config(self):
        proc, gui = run_main()
        proc.assert_not_called()
        gui.assert_called_once()
        self.assertEqual(gui.call_args[0][0].model, app.load_config().model)

    def test_input_only_uses_config_values_and_default_output(self):
        proc, gui = run_main("data/report.xlsx")
        gui.assert_not_called()
        in_path, out_path, cfg = proc.call_args[0]
        self.assertEqual(in_path, "data/report.xlsx")
        self.assertEqual(out_path, app.default_out("data/report.xlsx", cfg))
        base = app.load_config()
        self.assertEqual((cfg.model, cfg.host, cfg.mode, cfg.md), (base.model, base.host, base.mode, base.md))

    def test_command_line_overrides_config(self):
        proc, _ = run_main(
            "in.xlsx", "-o", "res.xlsx", "-m", "gemma2:2b", "--host", "http://h:9/", "--mode", "bilingual", "--no-md"
        )
        in_path, out_path, cfg = proc.call_args[0]
        self.assertEqual(out_path, "res.xlsx")
        self.assertEqual((cfg.model, cfg.host, cfg.mode, cfg.md), ("gemma2:2b", "http://h:9", "bilingual", False))

    def test_config_option_loads_given_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "my.toml"
            p.write_text('[ollama]\nmodel = "from-file"\n[output]\nsuffix = "_vi"\n', encoding="utf-8")
            proc, _ = run_main("in.xlsx", "-c", str(p))
            _, out_path, cfg = proc.call_args[0]
        self.assertEqual(cfg.model, "from-file")
        self.assertEqual(out_path, "in_vi.xlsx")

    def test_config_option_then_cli_override_wins(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "my.toml"
            p.write_text('[ollama]\nmodel = "from-file"\n', encoding="utf-8")
            proc, _ = run_main("in.xlsx", "-c", str(p), "-m", "from-cli")
        self.assertEqual(proc.call_args[0][2].model, "from-cli")

    def test_config_with_gui_when_no_input(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "my.toml"
            p.write_text('[ollama]\nmodel = "from-file"\n', encoding="utf-8")
            _, gui = run_main("-c", str(p))
        self.assertEqual(gui.call_args[0][0].model, "from-file")

    def test_missing_config_file_exits_with_message(self):
        with self.assertRaises(SystemExit) as cm:
            run_main("in.xlsx", "-c", "/không/tồn/tại.toml")
        self.assertIn("Lỗi cấu hình", str(cm.exception.code))

    def test_invalid_config_exits_with_message(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.toml"
            p.write_text('[translate]\nmode = "x"\n', encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                run_main("in.xlsx", "-c", str(p))
        self.assertIn("Lỗi cấu hình", str(cm.exception.code))

    def test_invalid_mode_argument_is_rejected_by_argparse(self):
        with self.assertRaises(SystemExit) as cm, mock.patch("sys.stderr"):
            run_main("in.xlsx", "--mode", "nope")
        self.assertEqual(cm.exception.code, 2)


class TestDefaultOut(unittest.TestCase):
    def test_suffix_from_config_and_extension_kept(self):
        cfg = default_cfg(suffix="_vi")
        self.assertEqual(app.default_out("/a/b/report.xlsx", cfg), str(Path("/a/b/report_vi.xlsx")))
        self.assertEqual(app.default_out("x.XLSM", cfg), "x_vi.XLSM")

    def test_default_suffix(self):
        self.assertEqual(app.default_out("report.xlsx", default_cfg()), "report_en.xlsx")


if __name__ == "__main__":
    unittest.main()
