"""Đếm token và thời gian sinh của model trong một lượt dịch (để ghi vào lịch sử).

Backend gọi `add(...)` sau mỗi lần gọi model; pipeline bọc mỗi file bằng start()/stop().
Nếu không có lượt nào đang theo dõi thì add() không làm gì.
"""
import threading
from dataclasses import dataclass

_lock = threading.Lock()
_active = None


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    gen_seconds: float = 0.0
    exact: bool = True  # False khi token chỉ là ước tính (chế độ thủ công)

    @property
    def tps(self):
        """Tốc độ sinh (token đầu ra / giây); None nếu chưa có dữ liệu."""
        return self.completion_tokens / self.gen_seconds if self.gen_seconds > 0 and self.completion_tokens else None


def start():
    global _active
    with _lock:
        _active = Usage()
        return _active


def stop():
    global _active
    with _lock:
        u, _active = _active, None
        return u


def add(prompt_tokens, completion_tokens, seconds):
    with _lock:
        if _active is None:
            return
        _active.calls += 1
        _active.prompt_tokens += int(prompt_tokens or 0)
        _active.completion_tokens += int(completion_tokens or 0)
        _active.gen_seconds += float(seconds or 0)


def estimate(pairs, tokenizer="o200k_base"):
    """Chế độ thủ công: token (ước lượng) của các cặp (gốc, bản dịch) trong lượt đang theo dõi."""
    from .tokens import TokenCounter  # noqa: PLC0415

    count = TokenCounter(tokenizer)
    p, c = sum(count(a) for a, _ in pairs), sum(count(b) for _, b in pairs)
    with _lock:
        if _active is not None:
            _active.prompt_tokens, _active.completion_tokens, _active.exact = p, c, False
