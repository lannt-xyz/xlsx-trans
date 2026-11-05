import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import fixtures  # noqa: F401  (thêm repo vào sys.path)
import app


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        # trỏ APP_DIR vào thư mục trống để test không phụ thuộc config.toml thật của repo
        patcher = mock.patch.object(app, "APP_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, rel, text):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p


class TestDefaults(ConfigTestCase):
    def test_no_config_files_uses_builtin_defaults(self):
        cfg = app.load_config()
        self.assertEqual(cfg.source_files, [])
        self.assertEqual(cfg.host, "http://localhost:11434")
        self.assertEqual(cfg.model, "qwen2.5:7b")
        self.assertEqual(cfg.mode, "replace")
        self.assertEqual(cfg.suffix, "_en")
        self.assertEqual(cfg.options, {"temperature": 0, "num_ctx": 4096})
        self.assertEqual(cfg.system_prompt, app.DEFAULT_SYSTEM_PROMPT)
        self.assertEqual(cfg.user_template, "{text}")
        self.assertTrue(all(cfg.targets.values()))
        self.assertEqual(set(cfg.targets), set(app.DEFAULT_CONFIG["targets"]))

    def test_default_regex_matches_japanese_only(self):
        cfg = app.load_config()
        for s in ["りんご", "カタカナ", "漢字", "ﾊﾝｶｸ", "ABC りんご"]:
            self.assertTrue(cfg.src_re.search(s), s)
        for s in ["ABC-123", "hello world", "123", "", "Ñandú"]:
            self.assertFalse(cfg.src_re.search(s), s)

    def test_default_config_object_is_not_mutated_by_loading(self):
        before = copy.deepcopy(app.DEFAULT_CONFIG)
        self.write("config.toml", '[ollama]\nmodel = "x"\n[ollama.options]\nnum_ctx = 1\n')
        app.load_config()
        self.assertEqual(app.DEFAULT_CONFIG, before)


class TestShippedConfig(unittest.TestCase):
    """config.toml và prompts/ trong repo phải khớp với giá trị mặc định trong code."""

    def test_shipped_config_equals_defaults(self):
        cfg = app.load_config(fixtures.ROOT / "config.toml")
        d = app.DEFAULT_CONFIG
        self.assertEqual(cfg.warnings, [])
        self.assertEqual(cfg.host, d["ollama"]["host"])
        self.assertEqual(cfg.model, d["ollama"]["model"])
        self.assertEqual(cfg.keep_alive, d["ollama"]["keep_alive"])
        self.assertEqual(cfg.timeout, d["ollama"]["timeout"])
        self.assertEqual(cfg.retries, d["ollama"]["retries"])
        self.assertEqual(cfg.options, d["ollama"]["options"])
        self.assertEqual(cfg.src_re.pattern, app.JP_PATTERN)
        self.assertEqual(cfg.mode, d["translate"]["mode"])
        self.assertEqual(cfg.cell_sep, d["translate"]["bilingual_cell_sep"])
        self.assertEqual(cfg.shape_sep, d["translate"]["bilingual_shape_sep"])
        self.assertEqual(cfg.targets, d["targets"])
        self.assertEqual(cfg.suffix, d["output"]["suffix"])
        self.assertEqual(cfg.md, d["output"]["markdown"])
        self.assertEqual(cfg.md_max_rows, d["output"]["markdown_max_rows"])
        self.assertEqual(cfg.md_max_cols, d["output"]["markdown_max_cols"])
        self.assertEqual(cfg.cache, d["output"]["cache"])

    def test_shipped_prompts_are_loaded(self):
        cfg = app.load_config(fixtures.ROOT / "config.toml")
        self.assertIn("{text}", cfg.user_template)
        self.assertIn("Japanese-to-English", cfg.system_prompt)
        self.assertEqual(
            cfg.system_prompt,
            (fixtures.ROOT / "prompts" / "system.txt").read_text(encoding="utf-8").strip(),
        )


class TestLoadingOrder(ConfigTestCase):
    def test_config_toml_overrides_defaults(self):
        self.write("config.toml", '[ollama]\nmodel = "gemma2:2b"\nretries = 5\n[output]\nsuffix = "_vi"\n')
        cfg = app.load_config()
        self.assertEqual((cfg.model, cfg.retries, cfg.suffix), ("gemma2:2b", 5, "_vi"))
        self.assertEqual(cfg.host, "http://localhost:11434")  # mục không khai báo giữ mặc định
        self.assertEqual([Path(f).name for f in cfg.source_files], ["config.toml"])

    def test_local_config_overrides_config_toml_and_options_are_merged(self):
        self.write("config.toml", '[ollama]\nmodel = "A"\n[ollama.options]\ntemperature = 0.5\n')
        self.write("config.local.toml", '[ollama]\nmodel = "B"\n[ollama.options]\nnum_ctx = 1024\n')
        cfg = app.load_config()
        self.assertEqual(cfg.model, "B")
        self.assertEqual(cfg.options, {"temperature": 0.5, "num_ctx": 1024})
        self.assertEqual([Path(f).name for f in cfg.source_files], ["config.toml", "config.local.toml"])

    def test_explicit_path_ignores_default_files(self):
        self.write("config.toml", '[ollama]\nmodel = "A"\n')
        self.write("config.local.toml", '[ollama]\nmodel = "B"\n')
        other = self.write("other/c.toml", '[ollama]\nmodel = "C"\n')
        cfg = app.load_config(other)
        self.assertEqual(cfg.model, "C")
        self.assertEqual(len(cfg.source_files), 1)

    def test_options_can_add_arbitrary_keys(self):
        self.write("config.toml", "[ollama.options]\ntop_p = 0.9\nnum_predict = 128\n")
        self.assertEqual(
            app.load_config().options, {"temperature": 0, "num_ctx": 4096, "top_p": 0.9, "num_predict": 128}
        )

    def test_partial_targets_keep_other_flags_true(self):
        self.write("config.toml", "[targets]\ncells = false\n")
        t = app.load_config().targets
        self.assertFalse(t["cells"])
        self.assertTrue(all(v for k, v in t.items() if k != "cells"))

    def test_host_trailing_slash_is_stripped(self):
        self.write("config.toml", '[ollama]\nhost = "http://h:1///"\n')
        self.assertEqual(app.load_config().host, "http://h:1")

    def test_literal_regex_and_separators_from_toml(self):
        self.write(
            "config.toml",
            "[translate]\nsource_pattern = '[\\u0400-\\u04ff]'\nbilingual_cell_sep = \" | \"\nmode = \"bilingual\"\n",
        )
        cfg = app.load_config()
        self.assertTrue(cfg.src_re.search("привет"))
        self.assertFalse(cfg.src_re.search("りんご"))
        self.assertEqual(cfg.cell_sep, " | ")
        self.assertEqual(cfg.mode, "bilingual")


class TestPrompts(ConfigTestCase):
    def test_prompts_are_read_relative_to_config_dir_and_stripped(self):
        self.write("sub/c.toml", '[prompt]\nsystem_file = "p/sys.txt"\nuser_file = "p/usr.txt"\n')
        self.write("sub/p/sys.txt", "\n  SYS PROMPT  \n\n")
        self.write("sub/p/usr.txt", "Translate:\n{text}\n")
        cfg = app.load_config(self.dir / "sub" / "c.toml")
        self.assertEqual(cfg.system_prompt, "SYS PROMPT")
        self.assertEqual(cfg.user_template, "Translate:\n{text}")
        self.assertEqual(cfg.warnings, [])

    def test_absolute_prompt_path(self):
        p = self.write("elsewhere/s.txt", "ABS")
        self.write("config.toml", f'[prompt]\nsystem_file = "{p.as_posix()}"\n')
        self.assertEqual(app.load_config().system_prompt, "ABS")

    def test_missing_prompt_file_warns_and_falls_back(self):
        self.write("config.toml", '[prompt]\nsystem_file = "nope.txt"\nuser_file = "nope2.txt"\n')
        cfg = app.load_config()
        self.assertEqual(cfg.system_prompt, app.DEFAULT_SYSTEM_PROMPT)
        self.assertEqual(cfg.user_template, app.DEFAULT_USER_TEMPLATE)
        self.assertEqual(len(cfg.warnings), 2)
        self.assertIn("system_file", cfg.warnings[0])
        self.assertIn("user_file", cfg.warnings[1])

    def test_empty_prompt_file_falls_back_without_warning(self):
        self.write("config.toml", '[prompt]\nsystem_file = "e.txt"\n')
        self.write("e.txt", "  \n\n")
        cfg = app.load_config()
        self.assertEqual(cfg.system_prompt, app.DEFAULT_SYSTEM_PROMPT)
        self.assertEqual(cfg.warnings, [])

    def test_default_prompt_paths_missing_is_silent(self):
        # không có config.toml / prompts/: dùng prompt trong code, không cảnh báo
        cfg = app.load_config()
        self.assertEqual(cfg.warnings, [])
        self.assertEqual(cfg.system_prompt, app.DEFAULT_SYSTEM_PROMPT)

    def test_config_without_prompt_section_and_no_prompt_files_is_silent(self):
        self.write("config.toml", '[ollama]\nmodel = "x"\n')
        cfg = app.load_config()
        self.assertEqual(cfg.warnings, [])
        self.assertEqual(cfg.user_template, app.DEFAULT_USER_TEMPLATE)

    def test_only_user_declared_paths_warn(self):
        self.write("config.toml", '[prompt]\nuser_file = "missing.txt"\n')  # system_file: mặc định, không warn
        cfg = app.load_config()
        self.assertEqual(len(cfg.warnings), 1)
        self.assertIn("user_file", cfg.warnings[0])

    def test_local_config_can_declare_prompt_paths(self):
        self.write("config.toml", '[ollama]\nmodel = "x"\n')
        self.write("config.local.toml", '[prompt]\nsystem_file = "mine.txt"\n')
        self.write("mine.txt", "LOCAL")
        cfg = app.load_config()
        self.assertEqual(cfg.system_prompt, "LOCAL")
        self.assertEqual(cfg.warnings, [])

    def test_empty_prompt_setting_uses_default(self):
        self.write("config.toml", '[prompt]\nsystem_file = ""\n')
        self.assertEqual(app.load_config().system_prompt, app.DEFAULT_SYSTEM_PROMPT)


class TestInvalidConfig(ConfigTestCase):
    def test_missing_explicit_file(self):
        with self.assertRaises(FileNotFoundError):
            app.load_config(self.dir / "nope.toml")

    def test_invalid_toml_syntax(self):
        p = self.write("bad.toml", "không phải toml ===")
        with self.assertRaises(ValueError) as cm:
            app.load_config(p)
        self.assertIn("bad.toml", str(cm.exception))

    def test_invalid_mode(self):
        self.write("config.toml", '[translate]\nmode = "x"\n')
        with self.assertRaisesRegex(ValueError, "mode"):
            app.load_config()

    def test_invalid_regex(self):
        self.write("config.toml", "[translate]\nsource_pattern = '['\n")
        with self.assertRaisesRegex(ValueError, "source_pattern"):
            app.load_config()


class TestSignature(ConfigTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = app.load_config()

    def changed(self, **kw):
        c = copy.copy(self.cfg)
        for k, v in kw.items():
            setattr(c, k, v)
        return c.signature()

    def test_signature_is_stable(self):
        self.assertEqual(self.cfg.signature(), app.load_config().signature())

    def test_changes_when_translation_inputs_change(self):
        base = self.cfg.signature()
        self.assertNotEqual(base, self.changed(model="other"))
        self.assertNotEqual(base, self.changed(system_prompt="other"))
        self.assertNotEqual(base, self.changed(user_template="X {text}"))
        self.assertNotEqual(base, self.changed(options={"temperature": 1}))

    def test_unchanged_for_settings_that_do_not_affect_translation(self):
        base = self.cfg.signature()
        for kw in [{"host": "http://other"}, {"mode": "bilingual"}, {"md": False}, {"suffix": "_x"}, {"retries": 9}]:
            self.assertEqual(base, self.changed(**kw), kw)


if __name__ == "__main__":
    unittest.main()
