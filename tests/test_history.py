"""Lịch sử dịch: đếm token/tốc độ, ghi file, đọc lại, CLI và cửa sổ GUI."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests import fixtures as fx
from tests.fixtures import FakeTranslator, default_cfg, patch_translate
from xlsx_trans import backend, cli, history, metrics, ollama, pipeline


class TestMetrics(unittest.TestCase):
    def test_add_only_when_active_and_tps(self):
        metrics.add(5, 5, 1)  # không có lượt nào → bỏ qua
        u = metrics.start()
        metrics.add(10, 20, 2.0)
        metrics.add(5, 10, 3.0)
        self.assertEqual((u.calls, u.prompt_tokens, u.completion_tokens), (2, 15, 30))
        self.assertAlmostEqual(u.tps, 6.0)
        self.assertIs(metrics.stop(), u)
        self.assertIsNone(metrics.Usage().tps)

    def test_ollama_reports_exact_counts(self):
        cfg = default_cfg()
        res = {"message": {"content": "Hi"}, "prompt_eval_count": 34, "eval_count": 8, "eval_duration": 2_000_000_000}
        u = metrics.start()
        with mock.patch.object(ollama, "_http_json", return_value=res):
            ollama.translate_text("こんにちは", cfg)
        metrics.stop()
        self.assertEqual((u.prompt_tokens, u.completion_tokens), (34, 8))
        self.assertAlmostEqual(u.tps, 4.0)


class TestHistoryFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.cfg = default_cfg(history_enabled=True, history_file=self.dir / "h.jsonl", history_max=3)

    def test_record_load_newest_first_and_bad_lines_skipped(self):
        for i in range(2):
            history.record(self.cfg, {"source": f"f{i}.xlsx", "prompt_tokens": i})
        with open(self.cfg.history_file, "a", encoding="utf-8") as f:
            f.write("{hỏng\n")
        got = history.load(self.cfg.history_file)
        self.assertEqual([e["source"] for e in got], ["f1.xlsx", "f0.xlsx"])
        self.assertIn("time", got[0])

    def test_disabled_writes_nothing(self):
        self.cfg.history_enabled = False
        history.record(self.cfg, {"source": "x"})
        self.assertFalse(self.cfg.history_file.exists())

    def test_trim_keeps_latest(self):
        self.cfg.history_max = 3
        for i in range(60):
            history.record(self.cfg, {"source": f"f{i}", "pad": "x" * 300})
        got = history.load(self.cfg.history_file)
        self.assertLessEqual(len(got), 60)
        self.assertEqual(got[0]["source"], "f59")
        self.assertEqual(len(got), 3)

    def test_summarize_and_csv(self):
        es = [{"prompt_tokens": 10, "completion_tokens": 20, "tps": 10.0, "seconds": 5},
              {"prompt_tokens": 1, "completion_tokens": 10, "tps": None, "seconds": 1}]
        s = history.summarize(es)
        self.assertEqual((s["runs"], s["prompt_tokens"], s["completion_tokens"]), (2, 11, 30))
        self.assertAlmostEqual(s["tps"], 10.0)
        p = self.dir / "o.csv"
        history.export_csv(es, p)
        self.assertIn("prompt_tokens", p.read_text(encoding="utf-8-sig").splitlines()[0])

    def test_clear(self):
        history.record(self.cfg, {"source": "x"})
        history.clear(self.cfg.history_file)
        self.assertEqual(history.load(self.cfg.history_file), [])


class TestPipelineRecordsHistory(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.src = fx.build_fixture(self.dir / "in.xlsx")
        self.cfg = default_cfg(history_enabled=True, history_file=self.dir / "h.jsonl")

    def test_one_entry_per_file_with_usage(self):
        def fake(text, cfg):
            metrics.add(10, 4, 0.5)
            return f"EN[{text}]"

        with mock.patch.object(backend, "translate_text", side_effect=fake):
            applied, errors = pipeline.process_xlsx(self.src, self.dir / "out.xlsx", self.cfg, log=lambda *_: None)
        (e,) = history.load(self.cfg.history_file)
        self.assertEqual(e["status"], "done")
        self.assertEqual(e["model"], self.cfg.model)
        self.assertEqual(e["segments"], applied)
        self.assertGreater(e["prompt_tokens"], 0)
        self.assertEqual(e["tps"], 8.0)

    def test_failed_run_is_recorded_as_error(self):
        with mock.patch.object(backend, "check", side_effect=ValueError("x")):
            with self.assertRaises(ValueError):
                pipeline.process_xlsx(self.src, self.dir / "out.xlsx", self.cfg, log=lambda *_: None)
        self.assertEqual(history.load(self.cfg.history_file)[0]["status"], "error")

    def test_stopped_run_status(self):
        with patch_translate(FakeTranslator()):
            pipeline.process_xlsx(self.src, self.dir / "out.xlsx", self.cfg, log=lambda *_: None, should_stop=lambda: True)
        self.assertEqual(history.load(self.cfg.history_file)[0]["status"], "stopped")

    def test_manual_backend_estimates_tokens(self):
        cfg = default_cfg(history_enabled=True, history_file=self.dir / "h2.jsonl", backend="manual", manual_tokenizer="estimate")
        cfg.refresh()
        with mock.patch.object(backend, "translate_text", FakeTranslator()):  # điền cache như khi đã dán kết quả từ chat
            pipeline.process_xlsx(self.src, self.dir / "o2.xlsx", cfg, log=lambda *_: None)
        (e,) = history.load(cfg.history_file)
        self.assertFalse(e["exact"])
        self.assertGreater(e["prompt_tokens"], 0)
        self.assertGreater(e["completion_tokens"], 0)
        self.assertIsNone(e["tps"])


class TestCli(unittest.TestCase):
    def test_print_history(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = default_cfg(history_enabled=True, history_file=Path(d) / "h.jsonl")
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli.print_history(cfg, 5)
            self.assertIn("Chưa có lịch sử", buf.getvalue())
            history.record(cfg, {"source": "/a/b.xlsx", "model": "qwen", "prompt_tokens": 12, "completion_tokens": 34,
                                 "tps": 5.5, "seconds": 65, "status": "done"})
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli.print_history(cfg, 5)
            out = buf.getvalue()
            for s in ("qwen", "b.xlsx", "5.5", "01:05", "Tổng 1 lượt"):
                self.assertIn(s, out)


def _tk_ok():
    try:
        import tkinter

        tkinter.Tk().destroy()
        return True
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_tk_ok(), "cần tkinter + màn hình (xvfb-run)")
class TestHistoryDialog(unittest.TestCase):
    def test_dialog_lists_entries(self):
        from xlsx_trans import config
        from xlsx_trans.gui import app as A
        from xlsx_trans.gui.history_dialog import HistoryDialog

        with tempfile.TemporaryDirectory() as d:
            cfg = config.load_config()
            cfg.history_enabled, cfg.history_file = True, Path(d) / "h.jsonl"
            history.record(cfg, {"source": "x/y.xlsx", "model": "m", "backend": "llama_cpp", "prompt_tokens": 1500,
                                 "completion_tokens": 300, "tps": 3.2, "seconds": 90, "status": "partial", "errors": 2})
            a = A.App(cfg)
            try:
                dlg = HistoryDialog(a)
                a.root.update()
                (row,) = dlg.tree.get_children()
                vals = dlg.tree.item(row, "values")
                self.assertEqual(vals[1], "y.xlsx")
                self.assertIn("llama_cpp", vals[2])
                self.assertEqual(vals[3], "1,500")
                self.assertIn("1 lượt", dlg.summary.get())
            finally:
                a.stop_flag = True
                a.bus.close()
                a.root.destroy()


if __name__ == "__main__":
    unittest.main()
