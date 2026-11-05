import json
import tempfile
import unittest
from pathlib import Path

from xlsx_trans.cache import TranslationCache


class TestTranslationCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "sub" / "c.json"

    def test_roundtrip_with_same_signature(self):
        c = TranslationCache(self.path, "sig1", model="m")
        c["りんご"] = "apple"
        c.save()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data, {"sig": "sig1", "model": "m", "map": {"りんご": "apple"}})
        again = TranslationCache(self.path, "sig1")
        self.assertIn("りんご", again)
        self.assertEqual(again.get("りんご"), "apple")
        self.assertEqual(len(again), 1)

    def test_different_signature_is_ignored(self):
        c = TranslationCache(self.path, "sig1")
        c["a"] = "b"
        c.save()
        self.assertEqual(len(TranslationCache(self.path, "sig2")), 0)

    def test_save_creates_parent_directories(self):
        c = TranslationCache(self.path, "s")
        c["a"] = "b"
        c.save()
        self.assertTrue(self.path.exists())

    def test_disabled_cache_keeps_memory_but_never_touches_disk(self):
        c = TranslationCache(self.path, "s", enabled=False)
        c["a"] = "b"
        self.assertIn("a", c)
        c.save()
        self.assertFalse(self.path.exists())

    def test_no_path_means_memory_only(self):
        c = TranslationCache(None, "s")
        c["a"] = "b"
        c.save()  # không lỗi
        self.assertEqual(c.get("a"), "b")
        self.assertFalse(c.enabled)

    def test_corrupt_or_unexpected_files_are_ignored(self):
        self.path.parent.mkdir(parents=True)
        for content in ["{không phải json", "[]", '"x"', "null"]:
            self.path.write_text(content, encoding="utf-8")
            self.assertEqual(len(TranslationCache(self.path, "s")), 0, content)

    def test_get_default_and_missing(self):
        c = TranslationCache(None, "s")
        self.assertIsNone(c.get("x"))
        self.assertEqual(c.get("x", "d"), "d")
        self.assertNotIn("x", c)

    def test_unwritable_location_does_not_raise(self):
        blocker = Path(self._tmp.name) / "file"
        blocker.write_text("x")
        c = TranslationCache(blocker / "c.json", "s")  # cha là một file => không ghi được
        c["a"] = "b"
        c.save()  # chỉ bỏ qua, không ném lỗi


if __name__ == "__main__":
    unittest.main()
