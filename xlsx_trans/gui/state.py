"""Trạng thái giao diện lưu giữa các lần mở (theme, kích thước cửa sổ, thư mục cuối)."""
import json
from pathlib import Path

from ..config import APP_DIR

DEFAULTS = {"theme": "light", "geometry": "", "last_dir": "", "log_open": True}
STATE_FILE = APP_DIR / ".ui_state.json"


class UiState(dict):
    def __init__(self, path=STATE_FILE):
        super().__init__(DEFAULTS)
        self.path = Path(path)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.update({k: v for k, v in data.items() if k in DEFAULTS and type(v) is type(DEFAULTS[k])})
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            self.path.write_text(json.dumps(dict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
