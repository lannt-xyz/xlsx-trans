"""Chạy model GGUF ngay trong tiến trình bằng llama-cpp-python (không cần Ollama, không có kết nối mạng).

Cài (tùy chọn):  pip install llama-cpp-python
Model được nạp một lần rồi dùng lại cho mọi đoạn / mọi file trong cùng lần chạy.
"""
import atexit
import collections
import importlib.util
import json
import os
import platform
import subprocess
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
    try:  # không import llama_cpp ở tiến trình chính (chính nó có thể là thứ gây lỗi)
        from importlib.metadata import version  # noqa: PLC0415

        ver = version("llama-cpp-python")
    except Exception:  # noqa: BLE001
        ver = "?"
    mp = Path(str(cfg.model_path))
    size = f"{mp.stat().st_size / 2**30:.2f}GB" if mp.is_file() else "KHÔNG TỒN TẠI"
    return (f"python={sys.executable} ({platform.python_version()}, {platform.machine()}); llama-cpp-python={ver}; "
            f"model={mp} ({size}); n_ctx={cfg.n_ctx}; n_threads={cfg.n_threads}; n_gpu_layers={cfg.n_gpu_layers}; "
            f"isolate={getattr(cfg, 'llama_isolate', False)}; params={params}; cwd={os.getcwd()}; luồng={threading.current_thread().name}")


class _Remote:
    """Giao diện giống Llama nhưng model nằm ở tiến trình con (llama_worker). Tiến trình con chết = NativeCrash."""

    def __init__(self, kwargs):
        root = Path(__file__).resolve().parent.parent  # chạy `-m` từ thư mục gốc để không bị module trong xlsx_trans che stdlib
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        self.tail = collections.deque(maxlen=30)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "xlsx_trans.llama_worker"], cwd=str(root), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            bufsize=1, creationflags=flags)
        threading.Thread(target=self._drain, daemon=True).start()
        atexit.register(self.close)
        try:
            self._call({"op": "load", "kwargs": kwargs})
        except BaseException:
            self.close()
            raise

    def _drain(self):
        for line in self.proc.stderr:
            self.tail.append(line.rstrip())

    def _call(self, req):
        line = ""
        try:
            self.proc.stdin.write(json.dumps(req, ensure_ascii=True) + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
        except (OSError, ValueError):
            pass
        if not line:
            try:
                code = self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                code = "?"
            err = " | ".join(list(self.tail)[-8:])
            raise NativeCrash(f"Tiến trình llama.cpp đã dừng đột ngột (mã thoát {code}). stderr: {err or '(trống)'}")
        msg = json.loads(line)
        if not msg.get("ok"):
            raise RuntimeError(msg.get("error", "lỗi không rõ"))
        return msg

    def create_chat_completion(self, messages, **params):
        return self._call({"op": "chat", "messages": messages, "params": params})["res"]

    def close(self):
        try:
            if self.proc.poll() is None:
                self.proc.stdin.write('{"op": "quit"}\n')
                self.proc.stdin.flush()
                self.proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass


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
        old = _loaded["llm"]
        if isinstance(old, _Remote):
            old.close()
        _loaded.update(key=None, llm=None)
        kwargs = {"model_path": str(Path(str(cfg.model_path)).resolve()), "n_ctx": cfg.n_ctx,
                  "n_gpu_layers": cfg.n_gpu_layers, "verbose": False}
        if cfg.n_threads > 0:
            kwargs["n_threads"] = cfg.n_threads
        _loaded["llm"] = _Remote(kwargs) if getattr(cfg, "llama_isolate", False) else _import_llama()(**kwargs)
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
        except NativeCrash:
            raise  # tiến trình con đã chết: không thử lại
        except Exception as e:  # noqa: BLE001
            last_err = e
            if "access violation" in str(e).lower():  # lỗi native, thử lại cũng vô ích
                raise NativeCrash(f"llama.cpp bị crash ({e}). Thông tin để chẩn đoán: {_diagnostics(cfg, params)}") from e
    raise RuntimeError(f"llama.cpp lỗi: {last_err}")
