"""Đếm token để chia khối gửi cho chat. Dùng tiktoken (o200k_base) nếu có, không thì ước lượng thận trọng."""
import os
import re
from pathlib import Path

# Thư mục lưu bảng từ vựng tiktoken tải về (một lần). Đặt sẵn TIKTOKEN_CACHE_DIR thì dùng giá trị đó.
CACHE_DIR = Path(__file__).resolve().parent.parent / "resources" / "tiktoken"

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿＀-￯]")


def estimate(text):
    """Ước lượng thiên về dư: mỗi ký tự CJK ~1 token, ký tự khác ~1 token / 3.5 ký tự."""
    cjk = len(_CJK.findall(text))
    return cjk + int((len(text) - cjk) / 3.5) + 1


class TokenCounter:
    def __init__(self, name="o200k_base"):
        self.name = name
        self.kind = "estimate"
        self._enc = None
        if name and name != "estimate":
            try:
                os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(CACHE_DIR))
                import tiktoken

                self._enc = tiktoken.get_encoding(name)
                self.kind = f"tiktoken:{name}"
            except Exception:  # noqa: BLE001  (chưa cài, hoặc chưa tải được bảng từ vựng lần đầu)
                self._enc = None

    def __call__(self, text):
        if self._enc is not None:
            return len(self._enc.encode(text, disallowed_special=()))
        return estimate(text)


def prefetch(name="o200k_base"):
    """Nạp bộ mã hóa (lần đầu sẽ tải bảng từ vựng từ mạng). Trả về (có dùng tiktoken không, thông báo)."""
    counter = TokenCounter(name)
    if counter._enc is None:
        return False, "Không nạp được tiktoken (chưa cài `pip install tiktoken`, hoặc không tải được bảng từ vựng)."
    return True, f"Đã sẵn sàng ({counter.kind}); bảng từ vựng lưu ở {os.environ.get('TIKTOKEN_CACHE_DIR')}"
