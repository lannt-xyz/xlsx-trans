"""Cache bản dịch {đoạn gốc: bản dịch}.

Lưu ra file JSON để chạy lại / tiếp tục không phải dịch lại. Cache chỉ được dùng lại khi chữ ký
(model + prompt + options) không đổi. Một đối tượng cache có thể dùng chung cho nhiều file
(khi dịch cả folder, chuỗi lặp lại giữa các file chỉ phải dịch một lần).
"""
import json
from pathlib import Path


class TranslationCache:
    def __init__(self, path, signature, enabled=True, model=""):
        self.path = Path(path) if path else None
        self.signature = signature
        self.model = model
        self.enabled = bool(enabled and self.path)
        self.map = {}
        if self.enabled:
            self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(data, dict) and data.get("sig") == self.signature:
            self.map = dict(data.get("map", {}))

    def __contains__(self, text):
        return text in self.map

    def __len__(self):
        return len(self.map)

    def get(self, text, default=None):
        return self.map.get(text, default)

    def __setitem__(self, text, translation):
        self.map[text] = translation

    def save(self):
        """Ghi ra đĩa (không làm gì nếu cache tắt). Lỗi ghi file bị bỏ qua: cache chỉ để tăng tốc."""
        if not self.enabled:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(
                    {"sig": self.signature, "model": self.model, "map": self.map},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass
