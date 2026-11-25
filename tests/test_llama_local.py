"""Backend nhúng file .gguf (llama-cpp-python được giả lập, không cần cài thật)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import fixtures as fx
from tests.fixtures import FakeTranslator, default_cfg, patch_translate
from xlsx_trans import backend, config, llama_local, ollama, pipeline


class FakeLlama:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.reply = "EN!"
        FakeLlama.instances.append(self)

    def create_chat_completion(self, messages, **params):
        self.calls.append((messages, params))
        if isinstance(self.reply, Exception):
            raise self.reply
        return {"choices": [{"message": {"content": self.reply}}]}


class LlamaCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.gguf = self.dir / "m.gguf"
        self.gguf.write_bytes(b"GGUF")
        FakeLlama.instances = []
        llama_local._loaded.update(key=None, llm=None)
        patcher = mock.patch.object(llama_local, "_import_llama", return_value=FakeLlama)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = default_cfg(backend="llama_cpp", model_path=self.gguf, system_prompt="SYS")
        self.cfg.refresh()


FAKE_LLAMA_CPP = """
import os


class Llama:
    def __init__(self, **kw):
        if kw["model_path"].endswith("bad.gguf"):
            raise OSError("exception: access violation reading 0x0000000000000000")
        self.kw = kw

    def create_chat_completion(self, messages, **params):
        text = messages[-1]["content"]
        if "DIE" in text:
            os._exit(3)
        if "VIOLATE" in text:
            raise OSError("exception: access violation reading 0x0000000000000000")
        return {"choices": [{"message": {"content": "EN:" + text}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
"""


class TestIsolatedWorker(unittest.TestCase):
    """Tiến trình con thật, với module llama_cpp giả đặt trước trên PYTHONPATH."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        (self.dir / "llama_cpp.py").write_text(FAKE_LLAMA_CPP, encoding="utf-8")
        env = mock.patch.dict("os.environ", {"PYTHONPATH": str(self.dir)})
        env.start()
        self.addCleanup(env.stop)
        self.gguf = self.dir / "m.gguf"
        self.gguf.write_bytes(b"GGUF")
        llama_local._loaded.update(key=None, llm=None)
        self.addCleanup(self._close)
        self.cfg = default_cfg(backend="llama_cpp", model_path=self.gguf, system_prompt="SYS", llama_isolate=True)
        self.cfg.refresh()

    def _close(self):
        old = llama_local._loaded["llm"]
        if isinstance(old, llama_local._Remote):
            old.close()
        llama_local._loaded.update(key=None, llm=None)

    def test_translates_through_child_process_and_reports_usage(self):
        from xlsx_trans import metrics

        u = metrics.start()
        self.assertEqual(llama_local.translate_text("こんにちは", self.cfg), "EN:こんにちは")
        metrics.stop()
        self.assertEqual((u.prompt_tokens, u.completion_tokens), (7, 3))
        self.assertIsInstance(llama_local._loaded["llm"], llama_local._Remote)

    def test_model_is_loaded_once_and_japanese_survives_the_pipe(self):
        a = llama_local.translate_text("日本語", self.cfg)
        pid = llama_local._loaded["llm"].proc.pid
        b = llama_local.translate_text("もう一度", self.cfg)
        self.assertEqual((a, b), ("EN:日本語", "EN:もう一度"))
        self.assertEqual(llama_local._loaded["llm"].proc.pid, pid)

    def test_native_error_in_child_becomes_native_crash_and_app_survives(self):
        with self.assertRaises(llama_local.NativeCrash) as cm:
            llama_local.translate_text("VIOLATE", self.cfg)
        self.assertIn("isolate=True", str(cm.exception))

    def test_child_dying_becomes_native_crash_with_exit_code(self):
        with self.assertRaises(llama_local.NativeCrash) as cm:
            llama_local.translate_text("DIE", self.cfg)
        self.assertIn("mã thoát 3", str(cm.exception))

    def test_load_failure_in_child_is_fatal(self):
        bad = self.dir / "bad.gguf"
        bad.write_bytes(b"GGUF")
        self.cfg.model_path = bad
        with self.assertRaises(llama_local.NativeCrash) as cm:
            llama_local.translate_text("x", self.cfg)
        self.assertIn("Không nạp được model", str(cm.exception))

    def test_missing_worker_file_gives_a_clear_message(self):
        with mock.patch.object(llama_local, "__file__", str(self.dir / "llama_local.py")):
            with self.assertRaises(llama_local.NativeCrash) as cm:
                llama_local.translate_text("x", self.cfg)
        self.assertIn("llama_worker.py", str(cm.exception))
        self.assertIn("git pull", str(cm.exception))

    def test_changing_model_restarts_child(self):
        llama_local.translate_text("a", self.cfg)
        first = llama_local._loaded["llm"]
        other = self.dir / "o.gguf"
        other.write_bytes(b"GGUF")
        self.cfg.model_path = other
        llama_local.translate_text("a", self.cfg)
        self.assertIsNot(llama_local._loaded["llm"], first)
        self.assertIsNotNone(first.proc.poll())  # tiến trình cũ đã thoát


class TestNativeCrash(LlamaCase):
    def crash(self):
        _ = FakeLlama  # mô phỏng ctypes: OSError "exception: access violation reading 0x0..."
        return OSError("exception: access violation reading 0x0000000000000000")

    def test_access_violation_raises_native_crash_without_retry(self):
        llama_local.translate_text("warm", self.cfg)
        FakeLlama.instances[0].reply = self.crash()
        with self.assertRaises(llama_local.NativeCrash) as cm:
            llama_local.translate_text("x", self.cfg)
        self.assertIn("n_ctx=", str(cm.exception))
        self.assertEqual(len(FakeLlama.instances[0].calls), 2)  # 1 warm + 1 lần lỗi, không retry

    def test_pipeline_aborts_run_on_native_crash(self):
        src = fx.build_fixture(self.dir / "in.xlsx")
        with mock.patch.object(backend, "check"), \
                mock.patch.object(backend, "translate_text", side_effect=llama_local.NativeCrash("boom")) as m:
            with self.assertRaises(llama_local.NativeCrash):
                pipeline.process_xlsx(src, self.dir / "out.xlsx", self.cfg, log=lambda *_: None)
        self.assertEqual(m.call_count, 1)

    def test_load_failure_is_fatal_and_reported_once(self):
        with mock.patch.object(llama_local, "_import_llama", side_effect=OSError("exception: access violation reading 0x0")):
            with self.assertRaises(llama_local.NativeCrash) as cm:
                llama_local.translate_text("x", self.cfg)
        self.assertIn("Không nạp được model", str(cm.exception))
        self.assertIn("n_gpu_layers=", str(cm.exception))

    def test_ordinary_errors_still_retry(self):
        llama_local.translate_text("warm", self.cfg)
        FakeLlama.instances[0].reply = RuntimeError("other")
        with self.assertRaises(RuntimeError):
            llama_local.translate_text("x", self.cfg)
        self.assertEqual(len(FakeLlama.instances[0].calls), 1 + self.cfg.retries + 1)


class TestLlamaTranslate(LlamaCase):
    def test_model_and_options_come_from_llama_section(self):
        self.assertEqual(self.cfg.model, "m.gguf")
        self.assertEqual(self.cfg.options, {"temperature": 0})

    def test_messages_and_params(self):
        self.cfg.options = {"temperature": 0.2, "num_predict": 64, "num_ctx": 999, "top_p": 0.9}
        self.assertEqual(llama_local.translate_text("こんにちは", self.cfg), "EN!")
        messages, params = FakeLlama.instances[0].calls[0]
        self.assertEqual(messages, ollama.build_messages("こんにちは", self.cfg))
        self.assertEqual(params, {"temperature": 0.2, "max_tokens": 64, "top_p": 0.9})

    def test_model_loaded_once_and_reused(self):
        for t in ("a", "b", "c"):
            llama_local.translate_text(t, self.cfg)
        self.assertEqual(len(FakeLlama.instances), 1)
        kw = FakeLlama.instances[0].kwargs
        self.assertEqual((kw["model_path"], kw["n_ctx"], kw["n_gpu_layers"]), (str(self.gguf), 4096, 0))
        self.assertNotIn("n_threads", kw)  # 0 = tự chọn

    def test_threads_passed_when_set_and_reload_when_settings_change(self):
        self.cfg.n_threads = 6
        llama_local.translate_text("a", self.cfg)
        self.assertEqual(FakeLlama.instances[0].kwargs["n_threads"], 6)
        self.cfg.n_ctx = 2048
        llama_local.translate_text("a", self.cfg)
        self.assertEqual(len(FakeLlama.instances), 2)

    def test_retry_then_success_and_give_up(self):
        self.cfg.retries = 1
        llama_local.translate_text("a", self.cfg)
        llm = FakeLlama.instances[0]
        llm.reply = RuntimeError("x")
        with self.assertRaisesRegex(RuntimeError, "llama.cpp lỗi"):
            llama_local.translate_text("a", self.cfg)
        self.assertEqual(len(llm.calls), 1 + 2)

    def test_empty_reply_is_error(self):
        self.cfg.retries = 0
        llama_local.translate_text("a", self.cfg)
        FakeLlama.instances[0].reply = "  "
        with self.assertRaises(RuntimeError):
            llama_local.translate_text("a", self.cfg)


class TestCheck(LlamaCase):
    def test_missing_gguf(self):
        self.cfg.model_path = self.dir / "none.gguf"
        with self.assertRaisesRegex(ValueError, "GGUF"):
            llama_local.check(self.cfg)

    def test_missing_library(self):
        with mock.patch("importlib.util.find_spec", return_value=None):
            with self.assertRaisesRegex(ValueError, "llama-cpp-python"):
                llama_local.check(self.cfg)

    def test_ok(self):
        with mock.patch("importlib.util.find_spec", return_value=object()):
            llama_local.check(self.cfg)


class TestDispatch(LlamaCase):
    def test_llama_backend_does_not_touch_ollama(self):
        with mock.patch.object(ollama, "_http_json", side_effect=AssertionError("không được gọi mạng")):
            self.assertEqual(backend.translate_text("a", self.cfg), "EN!")

    def test_ollama_backend_uses_ollama(self):
        cfg = default_cfg()
        fake = FakeTranslator()
        with patch_translate(fake):
            self.assertEqual(backend.translate_text("a", cfg), "EN[a]")
        self.assertEqual(FakeLlama.instances, [])

    def test_check_is_noop_for_ollama(self):
        backend.check(default_cfg())

    def test_pipeline_fails_fast_when_gguf_missing(self):
        src = fx.build_fixture(self.dir / "in.xlsx")
        self.cfg.model_path = self.dir / "none.gguf"
        with self.assertRaises(ValueError):
            pipeline.process_xlsx(src, self.dir / "o.xlsx", self.cfg, log=lambda m: None)
        self.assertFalse((self.dir / "o.xlsx").exists())

    def test_end_to_end_with_fake_llama(self):
        src = fx.build_fixture(self.dir / "in.xlsx")
        with mock.patch("importlib.util.find_spec", return_value=object()):
            applied, errors = pipeline.process_xlsx(src, self.dir / "o.xlsx", self.cfg, log=lambda m: None)
        self.assertEqual((applied, errors), (fx.UNIT_COUNT, 0))

    def test_signature_differs_between_backends(self):
        a, b = default_cfg(), default_cfg(backend="llama_cpp", model_path=self.gguf)
        b.refresh()
        self.assertNotEqual(a.signature(), b.signature())


class TestConfigSection(unittest.TestCase):
    def load(self, toml):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text(toml, encoding="utf-8")
            return config.load_config(p), Path(d)

    def test_defaults(self):
        cfg = default_cfg()
        self.assertEqual(cfg.backend, "ollama")
        self.assertEqual((cfg.n_ctx, cfg.n_threads, cfg.n_gpu_layers), (4096, 0, 0))

    def test_llama_backend_from_file_resolves_relative_path(self):
        cfg, d = self.load('[backend]\ntype = "llama_cpp"\n[llama_cpp]\nmodel_path = "models/q.gguf"\nn_threads = 6\n')
        self.assertEqual(cfg.backend, "llama_cpp")
        self.assertEqual(cfg.model_path, d / "models/q.gguf")
        self.assertEqual((cfg.model, cfg.n_threads), ("q.gguf", 6))
        self.assertEqual(cfg.ollama_model, "qwen2.5:7b")

    def test_invalid_backend(self):
        with self.assertRaisesRegex(ValueError, "backend.type"):
            self.load('[backend]\ntype = "gpt"\n')


if __name__ == "__main__":
    unittest.main()
