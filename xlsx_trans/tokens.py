"""Đếm token để chia khối gửi cho chat. Dùng tiktoken (o200k_base) nếu có, không thì ước lượng thận trọng."""
import re

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
                import tiktoken

                self._enc = tiktoken.get_encoding(name)
                self.kind = f"tiktoken:{name}"
            except Exception:  # noqa: BLE001  (chưa cài, hoặc chưa tải được bảng từ vựng lần đầu)
                self._enc = None

    def __call__(self, text):
        if self._enc is not None:
            return len(self._enc.encode(text, disallowed_special=()))
        return estimate(text)
