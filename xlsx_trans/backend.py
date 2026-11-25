"""Chọn cách chạy model: `ollama` (gọi HTTP tới Ollama) hoặc `llama_cpp` (nạp file .gguf ngay trong tiến trình).

Cũng là nơi áp dụng từ điển giữ nguyên tiếng Nhật (xem dictionary.py).
"""
import copy

from . import ollama
from .dictionary import Dictionary

RETRY_TEMPERATURE = 0.4  # nhiệt độ tối thiểu cho lần thử lại khi model làm mất ký hiệu từ điển


def check(cfg):
    """Kiểm tra nhanh trước khi dịch; ném ValueError với thông báo rõ ràng nếu backend chưa dùng được."""
    if cfg.backend == "llama_cpp":
        from . import llama_local

        llama_local.check(cfg)


def _translate_raw(text, cfg):
    if cfg.backend == "manual":
        raise RuntimeError("chưa có bản dịch trong cache (chế độ thủ công: dịch bằng chat rồi nhập kết quả)")
    if cfg.backend == "llama_cpp":
        from . import llama_local

        return llama_local.translate_text(text, cfg)
    return ollama.translate_text(text, cfg)


def translate_text(text, cfg):
    """Dịch một đoạn; các từ trong cfg.dictionary được giữ nguyên tiếng Nhật."""
    dic = getattr(cfg, "dictionary", None)
    if not dic:
        return _translate_raw(text, cfg)
    masked, mapping = dic.protect(text)
    if not mapping:
        return _translate_raw(text, cfg)
    if not cfg.src_re.search(Dictionary._PH_RE.sub("", masked)):
        return text  # toàn từ khóa, không có gì để dịch
    c = copy.copy(cfg)
    c.system_prompt = (cfg.system_prompt + "\n\n" + cfg.placeholder_note).strip()
    outs = []
    # Lần 1: nhiệt độ như cấu hình. Lần 2: tăng nhiệt độ (ở 0 thì thử lại ra y hệt) và bỏ seed cố định.
    for attempt in range(2):
        if attempt:
            c.options = dict(cfg.options)
            c.options["temperature"] = max(float(c.options.get("temperature") or 0), RETRY_TEMPERATURE)
            c.options.pop("seed", None)
        out = _translate_raw(masked, c)
        restored, ok = Dictionary.restore(out, mapping)
        if ok:
            return restored
        outs.append(out)
    # Lần 3: không dùng ký hiệu; dặn giữ nguyên các từ rồi kiểm tra từ nào cũng còn trong kết quả.
    terms = list(mapping.values())
    f = copy.copy(cfg)
    f.system_prompt = (cfg.system_prompt + "\n\n" + Dictionary.keep_note(terms)).strip()
    out = _translate_raw(text, f)
    if all(t in out for t in terms):
        return out
    outs.append(out)
    raise RuntimeError(
        "Model làm mất từ khóa trong từ điển (ký hiệu [[n]]); giữ nguyên bản gốc. "
        "Model trả về: " + " | ".join(repr(o[:120]) for o in outs))
