"""Test phần logic thuần của giao diện (không cần tkinter) + lưu cấu hình riêng + ghi từ điển."""
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import default_cfg
from xlsx_trans import config, dictionary
from xlsx_trans.gui import settings_model as sm
from xlsx_trans.gui.state import UiState
from xlsx_trans.gui.util import classify_log, estimate_eta, format_duration

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib


class TestUtil(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(format_duration(83), "01:23")
        self.assertEqual(format_duration(3700), "1:01:40")
        self.assertEqual(format_duration(-5), "00:00")

    def test_classify_log(self):
        self.assertEqual(classify_log("LỖI: hỏng"), "error")
        self.assertEqual(classify_log("Cảnh báo: x"), "warn")
        self.assertEqual(classify_log("Hoàn tất"), "ok")
        self.assertEqual(classify_log("dịch 3 đoạn"), "info")

    def test_eta(self):
        self.assertIsNone(estimate_eta(1, 0, 1, 0.5))  # quá sớm
        self.assertAlmostEqual(estimate_eta(10, 0, 1, 0.5), 10)
        self.assertAlmostEqual(estimate_eta(20, 1, 4, 0.0), 60)
        self.assertIsNone(estimate_eta(10, 0, 0, 0))


class TestState(unittest.TestCase):
    def test_roundtrip_and_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            s = UiState(p)
            s["theme"] = "dark"
            s.save()
            self.assertEqual(UiState(p)["theme"], "dark")
            p.write_text("{bad", encoding="utf-8")
            self.assertIn("theme", UiState(p))


class TestConfigSave(unittest.TestCase):
    def test_dump_toml_roundtrip(self):
        data = {"a": 1, "s": 'x"y\\z\nq', "t": {"on": True, "f": 1.5, "l": ["a", "b"]}}
        self.assertEqual(tomllib.loads(config.dump_toml(data)), data)

    def test_save_overrides_merges_and_deletes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "local.toml"
            config.save_overrides({"x": {"a": 1, "b": 2}}, p)
            config.save_overrides({"x": {"a": 5, "b": None}}, p)
            self.assertEqual(tomllib.loads(p.read_text(encoding="utf-8")), {"x": {"a": 5}})


class TestSettingsModel(unittest.TestCase):
    def test_every_field_resolves_against_defaults(self):
        vals = sm.defaults()
        self.assertEqual(set(vals), {f.key for f in sm.FIELDS})

    def test_parse_value_validates(self):
        f = next(x for x in sm.FIELDS if x.kind == "int")
        with self.assertRaises(ValueError):
            sm.parse_value(f, "abc")
        self.assertIsInstance(sm.parse_value(f, str(max(f.minimum or 0, 1) + 1)), int)
        r = next(x for x in sm.FIELDS if x.kind == "regex")
        with self.assertRaises(ValueError):
            sm.parse_value(r, "(")

    def test_overrides_only_changed(self):
        cfg = default_cfg()
        init = sm.read_values(cfg)
        self.assertEqual(sm.overrides(init, dict(init)), {})
        f = next(x for x in sm.FIELDS if x.kind == "int")
        new = dict(init)
        new[f.key] = (init[f.key] or 0) + 1
        o = sm.overrides(init, new)
        node = o
        for part in f.path:
            node = node[part]
        self.assertEqual(node, new[f.key])


class TestDictionaryWrite(unittest.TestCase):
    def test_write_keeps_header_comment(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "d.txt"
            p.write_text("# ghi chú\n\n[screen]\n注文\n", encoding="utf-8")
            header = dictionary.split_header(p.read_text(encoding="utf-8"))
            self.assertIn("ghi chú", header)
            dictionary.write_entries(p, {"screen": ["注文"], "name": ["顧客"]})
            text = p.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# ghi chú"))
            self.assertIn("顧客", text)


def _tk_ok():
    try:
        import tkinter

        r = tkinter.Tk()
        r.destroy()
        return True
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_tk_ok(), "cần tkinter + màn hình (xvfb-run)")
class TestGuiSmoke(unittest.TestCase):
    def test_main_window_settings_and_theme(self):
        from xlsx_trans.gui import app as A
        from xlsx_trans.gui.settings_dialog import SettingsDialog

        with tempfile.TemporaryDirectory() as d:
            import xlsx_trans.gui.state as st

            old = st.STATE_FILE
            a = A.App(config.load_config(None))
            a.state.path = Path(d) / "s.json"
            try:
                a.root.update()
                SettingsDialog(a, None)
                a.root.update()
                a.toggle_theme()
                a.root.update()
                a.on_close()
            finally:
                st.STATE_FILE = old
            self.assertTrue((Path(d) / "s.json").exists())


if __name__ == "__main__":
    unittest.main()
