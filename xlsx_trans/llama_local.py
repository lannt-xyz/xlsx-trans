"""Chạy model GGUF ngay trong tiến trình bằng llama-cpp-python (không cần Ollama, không có kết nối mạng).

Cài (tùy chọn):  pip install llama-cpp-python
Model được nạp một lần rồi dùng lại cho mọi đoạn / mọi file trong cùng lần chạy.
"""
import importlib.util
import os
import platform
import sys
import threading
import time
from pathlib import Path

from . import metrics
from .ollama import build_messages

_loaded = {"key": None, "llm": None}

# options (theo tên của Ollama) -> tham số create_chat_completion
_OPTION_MAP = {
    "temperature": "temperature",
    "top_p": "top_p",
    "top_k": "top_k",
    "repeat_penalty": "repeat_penalty",
    "seed": "seed",
    "num_predict": "max_tokens",
    "max_tokens": "max_tokens",
}


class NativeCrash(RuntimeError):
    """Thư viện llama.cpp (tầng C++) bị crash: các đoạn sau sẽ lỗi y hệt nên phải dừng cả lượt dịch."""


def _diagnostics(cfg, params):
    try:
        import llama_cpp  # noqa: PLC0415

        ver = getattr(llama_cpp, "__version__", "?")
    except Exception:  # noqa: BLE001
        ver = "?"
    mp = Path(str(cfg.model_path))
    size = f"{mp.stat().st_size / 2**30:.2f}GB" if mp.is_file() else "KHÔNG TỒN TẠI"
    return (f"python={sys.executable} ({platform.python_version()}, {platform.machine()}); llama-cpp-python={ver}; "
            f"model={mp} ({size}); n_ctx={cfg.n_ctx}; n_threads={cfg.n_threads}; n_gpu_layers={cfg.n_gpu_layers}; "
            f"params={params}; cwd={os.getcwd()}; luồng={threading.current_thread().name}")


def _import_llama():
    from llama_cpp import Llama  # noqa: PLC0415

    return Llama


def check(cfg):
    path = Path(str(cfg.model_path))
    if not path.is_file():
        raise ValueError(
            f"Không thấy file model GGUF: {path}\n"
            "Tải file .gguf về rồi đặt đường dẫn ở llama_cpp.model_path (hoặc --model-path)."
        )
    if importlib.util.find_spec("llama_cpp") is None:
        raise ValueError("Thiếu thư viện llama-cpp-python. Cài bằng:  pip install llama-cpp-python")


def _get_llm(cfg):
    key = (str(cfg.model_path), cfg.n_ctx, cfg.n_threads, cfg.n_gpu_layers)
    if _loaded["key"] != key:
        kwargs = {"model_path": str(cfg.model_path), "n_ctx": cfg.n_ctx, "n_gpu_layers": cfg.n_gpu_layers, "verbose": False}
        if cfg.n_threads > 0:
            kwargs["n_threads"] = cfg.n_threads
        _loaded["llm"] = _import_llama()(**kwargs)
        _loaded["key"] = key
    return _loaded["llm"]


def translate_text(text, cfg):
    params = {}
    for k, v in cfg.options.items():
        if k in _OPTION_MAP:
            params[_OPTION_MAP[k]] = v
    try:
        llm = _get_llm(cfg)
    except Exception as e:  # noqa: BLE001  (nạp model hỏng thì mọi đoạn sau cũng hỏng: dừng cả lượt)
        raise NativeCrash(f"Không nạp được model llama.cpp ({e}). Thông tin để chẩn đoán: {_diagnostics(cfg, params)}") from e
    last_err = None
    for _ in range(cfg.retries + 1):
        try:
            t0 = time.perf_counter()
            res = llm.create_chat_completion(messages=build_messages(text, cfg), **params)
            usage = res.get("usage") or {}
            metrics.add(usage.get("prompt_tokens"), usage.get("completion_tokens"), time.perf_counter() - t0)
            out = res["choices"][0]["message"]["content"].strip()
            if out:
                return out
        except Exception as e:  # noqa: BLE001
            last_err = e
            if "access violation" in str(e).lower():  # lỗi native, thử lại cũng vô ích
                raise NativeCrash(f"llama.cpp bị crash ({e}). Thông tin để chẩn đoán: {_diagnostics(cfg, params)}") from e
    raise RuntimeError(f"llama.cpp lỗi: {last_err}")
