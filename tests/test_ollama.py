import copy
import unittest
from unittest import mock

from tests.fixtures import default_cfg
import app


def reply(text):
    return {"message": {"content": text}}


class TestBuildMessages(unittest.TestCase):
    def setUp(self):
        self.cfg = default_cfg(system_prompt="SYS")

    def test_system_then_user_with_default_template(self):
        self.assertEqual(
            app.build_messages("こんにちは", self.cfg),
            [{"role": "system", "content": "SYS"}, {"role": "user", "content": "こんにちは"}],
        )

    def test_template_placeholder_is_replaced(self):
        self.cfg.user_template = "Dịch:\n<<<{text}>>>\nChỉ trả về bản dịch."
        msgs = app.build_messages("注意", self.cfg)
        self.assertEqual(msgs[1]["content"], "Dịch:\n<<<注意>>>\nChỉ trả về bản dịch.")

    def test_template_without_placeholder_is_prepended(self):
        self.cfg.user_template = "Translate to English."
        self.assertEqual(app.build_messages("注意", self.cfg)[1]["content"], "Translate to English.\n\n注意")

    def test_other_braces_in_template_and_text_are_untouched(self):
        self.cfg.user_template = 'JSON: {"k": 1} {text}'
        msgs = app.build_messages("{x} {text}", self.cfg)
        self.assertEqual(msgs[1]["content"], 'JSON: {"k": 1} {x} {text}')

    def test_empty_system_prompt_is_omitted(self):
        self.cfg.system_prompt = ""
        msgs = app.build_messages("a", self.cfg)
        self.assertEqual([m["role"] for m in msgs], ["user"])


class TestTranslateText(unittest.TestCase):
    def setUp(self):
        self.cfg = default_cfg()

    def test_request_shape_and_response_is_stripped(self):
        with mock.patch.object(app, "_http_json", return_value=reply(" Hello \n")) as m:
            out = app.translate_text("こんにちは", self.cfg)
        self.assertEqual(out, "Hello")
        m.assert_called_once()
        (url, payload), kw = m.call_args
        self.assertEqual(url, "http://localhost:11434/api/chat")
        self.assertEqual(kw["timeout"], self.cfg.timeout)
        self.assertEqual(payload["model"], self.cfg.model)
        self.assertIs(payload["stream"], False)
        self.assertEqual(payload["keep_alive"], "30m")
        self.assertEqual(payload["options"], {"temperature": 0, "num_ctx": 4096})
        self.assertEqual(payload["messages"], app.build_messages("こんにちは", self.cfg))

    def test_options_are_copied_not_shared(self):
        with mock.patch.object(app, "_http_json", return_value=reply("x")) as m:
            app.translate_text("a", self.cfg)
        payload = m.call_args[0][1]
        self.assertEqual(payload["options"], self.cfg.options)
        self.assertIsNot(payload["options"], self.cfg.options)

    def test_custom_host_model_options(self):
        cfg = copy.copy(self.cfg)
        cfg.host, cfg.model, cfg.options = "http://h:9", "m1", {"temperature": 0.3, "top_p": 0.8}
        with mock.patch.object(app, "_http_json", return_value=reply("x")) as m:
            app.translate_text("a", cfg)
        (url, payload), _ = m.call_args
        self.assertEqual(url, "http://h:9/api/chat")
        self.assertEqual((payload["model"], payload["options"]), ("m1", {"temperature": 0.3, "top_p": 0.8}))

    def test_keep_alive_omitted_when_empty(self):
        self.cfg.keep_alive = ""
        with mock.patch.object(app, "_http_json", return_value=reply("x")) as m:
            app.translate_text("a", self.cfg)
        self.assertNotIn("keep_alive", m.call_args[0][1])

    def test_retries_after_exception_then_succeeds(self):
        self.cfg.retries = 2
        with mock.patch.object(app, "_http_json", side_effect=[OSError("down"), reply("ok")]) as m:
            self.assertEqual(app.translate_text("a", self.cfg), "ok")
        self.assertEqual(m.call_count, 2)

    def test_retries_when_response_is_empty(self):
        self.cfg.retries = 2
        with mock.patch.object(app, "_http_json", side_effect=[reply("  "), reply("ok")]) as m:
            self.assertEqual(app.translate_text("a", self.cfg), "ok")
        self.assertEqual(m.call_count, 2)

    def test_gives_up_after_retries_plus_one_attempts(self):
        self.cfg.retries = 2
        with mock.patch.object(app, "_http_json", side_effect=OSError("down")) as m:
            with self.assertRaisesRegex(RuntimeError, "Ollama lỗi"):
                app.translate_text("a", self.cfg)
        self.assertEqual(m.call_count, 3)

    def test_zero_retries_means_single_attempt(self):
        self.cfg.retries = 0
        with mock.patch.object(app, "_http_json", side_effect=OSError("down")) as m:
            with self.assertRaises(RuntimeError):
                app.translate_text("a", self.cfg)
        self.assertEqual(m.call_count, 1)

    def test_malformed_response_is_an_error(self):
        self.cfg.retries = 0
        with mock.patch.object(app, "_http_json", return_value={"oops": 1}):
            with self.assertRaises(RuntimeError):
                app.translate_text("a", self.cfg)


class TestListModels(unittest.TestCase):
    def test_returns_names(self):
        with mock.patch.object(app, "_http_json", return_value={"models": [{"name": "a"}, {"name": "b:7b"}]}) as m:
            self.assertEqual(app.list_models("http://h:1"), ["a", "b:7b"])
        self.assertEqual(m.call_args[0][0], "http://h:1/api/tags")
        self.assertEqual(m.call_args[1]["timeout"], 5)

    def test_returns_empty_list_on_error(self):
        with mock.patch.object(app, "_http_json", side_effect=OSError("down")):
            self.assertEqual(app.list_models("http://h:1"), [])

    def test_missing_models_key(self):
        with mock.patch.object(app, "_http_json", return_value={}):
            self.assertEqual(app.list_models("http://h:1"), [])


if __name__ == "__main__":
    unittest.main()
