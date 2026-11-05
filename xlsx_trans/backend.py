"""Chọn cách chạy model: `ollama` (gọi HTTP tới Ollama) hoặc `llama_cpp` (nạp file .gguf ngay trong tiến trình)."""
from . import ollama


def check(cfg):
    """Kiểm tra nhanh trước khi dịch; ném ValueError với thông báo rõ ràng nếu backend chưa dùng được."""
    if cfg.backend == "llama_cpp":
        from . import llama_local

        llama_local.check(cfg)


def translate_text(text, cfg):
    if cfg.backend == "llama_cpp":
        from . import llama_local

        return llama_local.translate_text(text, cfg)
    return ollama.translate_text(text, cfg)
