"""Nạp cấu hình (config.toml + config.local.toml) và prompt. Giá trị mặc định nằm ở đây.

Ý nghĩa từng mục: xem config.toml.
"""
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

from .dictionary import PLACEHOLDER_NOTE, Dictionary

try:
    import tomllib
except ImportError:  # Python < 3.11
    try:
        import tomli as tomllib
    except ImportError:  # pragma: no cover
        sys.exit("Python < 3.11 cần thư viện tomli. Cài bằng:  pip install tomli")

# Thư mục gốc của repo (chứa config.toml, prompts/, app.py)
APP_DIR = Path(__file__).resolve().parent.parent

# Hiragana, Katakana, Kanji, half-width Katakana
JP_PATTERN = r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]"

DEFAULT_SYSTEM_PROMPT = (
    "You are a professional Japanese-to-English translator working on spreadsheet text. "
    "Translate the user's text into natural, concise English. "
    "Rules: output ONLY the translation, no explanations, no quotes, no notes. "
    "Keep numbers, codes, product IDs, URLs, English words and symbols unchanged. "
    "Keep line breaks as they are. If part of the text is already English, keep it."
)
DEFAULT_USER_TEMPLATE = "{text}"
DEFAULT_MANUAL_INSTRUCTION = (
    "You will receive numbered items from a spreadsheet, after the line ITEMS:. "
    "Translate every item from Japanese to English following the rules above. "
    "Reply with exactly the same items in the same order, one per line, in the format `[n] translation`, "
    "using the same number n. Do not add, merge, skip or reorder items, and add no commentary or code fences. "
    "`<br>` marks a line break inside an item; keep it as `<br>`. "
    "Keep placeholders such as [[1]] unchanged."
)

BACKENDS = ("ollama", "llama_cpp", "manual")

DEFAULT_CONFIG = {
    "backend": {"type": "ollama"},
    "llama_cpp": {
        "model_path": "models/model.gguf",
        "n_ctx": 4096,
        "n_threads": 0,
        "n_gpu_layers": 0,
        "options": {"temperature": 0},
    },
    "ollama": {
        "host": "http://localhost:11434",
        "model": "qwen2.5:7b",
        "keep_alive": "30m",
        "timeout": 600,
        "retries": 2,
        "options": {"temperature": 0, "num_ctx": 4096},
    },
    "prompt": {
        "system_file": "prompts/system.txt",
        "user_file": "prompts/user.txt",
    },
    "translate": {
        "source_pattern": JP_PATTERN,
        "mode": "replace",
        "bilingual_cell_sep": "\n",
        "bilingual_shape_sep": " / ",
    },
    "targets": {
        "cells": True,
        "shapes": True,
        "charts": True,
        "diagrams": True,
        "comments": True,
        "table_headers": True,
    },
    "output": {
        "suffix": "_en",
        "markdown": True,
        "markdown_suffix": "_md",
        "markdown_max_rows": 20000,
        "markdown_max_cols": 200,
        "cache": True,
    },
    "dictionary": {
        "enabled": True,
        "files": ["resources/dictionary.txt"],
        "suggest": True,
        "suggest_max": 50,
        "ignore_file": "resources/dictionary.ignore.txt",
        "placeholder_note": PLACEHOLDER_NOTE,
    },
    "manual": {
        "tokenizer": "o200k_base",
        "block_tokens": 6000,
        "block_max_items": 300,
        "instruction_file": "prompts/manual.txt",
    },
    "batch": {
        "recursive": True,
        "continue_on_error": True,
    },
}


class Config:
    """Cấu hình đã nạp. Có thể copy.copy() rồi đổi thuộc tính (GUI / tham số dòng lệnh làm vậy)."""

    def reload_dictionary(self):
        """Nạp lại từ điển từ self.dict_files (GUI gọi sau khi người dùng sửa)."""
        if not self.dict_enabled:
            self.dictionary = Dictionary()
            self.ignored = set()
            return
        missing = []
        self.dictionary = Dictionary.load(self.dict_files, missing)
        self.dict_missing = missing
        from .suggest import load_ignored

        self.ignored = load_ignored(self.dict_ignore_file)

    def refresh(self):
        """Tính lại `model` và `options` theo backend đang chọn (gọi sau khi đổi backend/model/model_path)."""
        if self.backend == "manual":
            self.model = "manual"
            self.options = {}
        elif self.backend == "llama_cpp":
            self.model = Path(str(self.model_path)).name
            self.options = dict(self.llama_options)
        else:
            self.model = self.ollama_model
            self.options = dict(self.ollama_options)

    def signature(self):
        """Dấu vân tay của những thứ ảnh hưởng tới bản dịch; đổi thì cache cũ không dùng lại."""
        parts = [self.model, self.system_prompt, self.user_template, self.options]
        if self.backend != "ollama":
            parts.append(self.backend)
        if self.dictionary:  # chỉ khi có từ điển, để cache cũ (không dùng từ điển) vẫn hợp lệ
            parts += [self.dictionary.signature(), self.placeholder_note]
        blob = json.dumps(parts, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def deep_merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v


def read_text_setting(rel, base_dir, default, warnings, label, warn=True):
    if not rel:
        return default
    p = Path(str(rel)).expanduser()
    if not p.is_absolute():
        p = base_dir / p
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        if warn:  # đường dẫn mặc định (không do config khai báo) thiếu file thì lặng lẽ dùng prompt trong code
            warnings.append(f"Không đọc được {label} ({p}) — dùng prompt mặc định trong code.")
        return default
    return text or default


def load_config(path=None):
    """Nạp config. path=None: config.toml rồi config.local.toml trong thư mục gốc (nếu có)."""
    data = copy.deepcopy(DEFAULT_CONFIG)
    user_data = {}  # chỉ những gì file cấu hình tự khai báo (để biết đường dẫn nào là do người dùng đặt)
    if path:
        p = Path(path).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"Không thấy file cấu hình: {p}")
        files = [p]
    else:
        files = [f for f in (APP_DIR / "config.toml", APP_DIR / "config.local.toml") if f.is_file()]
    for f in files:
        try:
            with open(f, "rb") as fh:
                loaded = tomllib.load(fh)
            deep_merge(data, copy.deepcopy(loaded))
            deep_merge(user_data, loaded)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"Không đọc được {f}: {e}") from e
    base_dir = files[-1].parent if files else APP_DIR

    c = Config()
    c.source_files = [str(f) for f in files]
    c.warnings = []

    c.backend = str(data["backend"]["type"])
    if c.backend not in BACKENDS:
        raise ValueError(f'backend.type phải là một trong: {", ".join(BACKENDS)}.')
    lc = data["llama_cpp"]
    mp = Path(str(lc["model_path"])).expanduser()
    c.model_path = mp if mp.is_absolute() else base_dir / mp
    c.n_ctx = int(lc["n_ctx"])
    c.n_threads = int(lc["n_threads"])
    c.n_gpu_layers = int(lc["n_gpu_layers"])
    c.llama_options = dict(lc.get("options") or {})

    o = data["ollama"]
    c.host = str(o["host"]).rstrip("/")
    c.ollama_model = str(o["model"])
    c.keep_alive = str(o.get("keep_alive", "") or "")
    c.timeout = float(o["timeout"])
    c.retries = int(o["retries"])
    c.ollama_options = dict(o.get("options") or {})

    pr = data["prompt"]
    set_by_user = user_data.get("prompt", {})
    c.system_prompt = read_text_setting(
        pr.get("system_file"), base_dir, DEFAULT_SYSTEM_PROMPT, c.warnings, "prompt.system_file",
        warn="system_file" in set_by_user,
    )
    c.user_template = read_text_setting(
        pr.get("user_file"), base_dir, DEFAULT_USER_TEMPLATE, c.warnings, "prompt.user_file",
        warn="user_file" in set_by_user,
    )

    t = data["translate"]
    try:
        c.src_re = re.compile(t["source_pattern"])
    except re.error as e:
        raise ValueError(f"translate.source_pattern không hợp lệ: {e}") from e
    c.mode = t["mode"]
    if c.mode not in ("replace", "bilingual"):
        raise ValueError('translate.mode phải là "replace" hoặc "bilingual".')
    c.cell_sep = str(t["bilingual_cell_sep"])
    c.shape_sep = str(t["bilingual_shape_sep"])

    c.targets = {k: bool(v) for k, v in data["targets"].items()}
    for k in DEFAULT_CONFIG["targets"]:
        c.targets.setdefault(k, True)
    if c.targets["table_headers"] != c.targets["cells"]:
        # Excel báo file lỗi nếu tên cột Table khác chữ ở ô tiêu đề, nên hai mục này phải đi cùng nhau
        c.warnings.append('targets.table_headers luôn theo targets.cells (tên cột Table phải trùng ô tiêu đề); đã đặt cùng giá trị.')
        c.targets["table_headers"] = c.targets["cells"]

    out = data["output"]
    c.suffix = str(out["suffix"])
    c.md = bool(out["markdown"])
    c.md_suffix = str(out["markdown_suffix"])
    c.md_max_rows = int(out["markdown_max_rows"])
    c.md_max_cols = int(out["markdown_max_cols"])
    c.cache = bool(out["cache"])

    d = data["dictionary"]
    c.dict_enabled = bool(d["enabled"])
    declared = "files" in user_data.get("dictionary", {})
    files = d["files"] if isinstance(d["files"], list) else [d["files"]]
    c.dict_files = []
    for f in files:
        fp = Path(str(f)).expanduser()
        c.dict_files.append(fp if fp.is_absolute() else base_dir / fp)
    c.suggest = bool(d["suggest"])
    c.suggest_max = int(d["suggest_max"])
    ip = Path(str(d["ignore_file"])).expanduser()
    c.dict_ignore_file = ip if ip.is_absolute() else base_dir / ip
    c.ignored = set()
    c.placeholder_note = str(d["placeholder_note"] or PLACEHOLDER_NOTE)
    c.dictionary = Dictionary()
    c.dict_missing = []
    c.reload_dictionary()
    if declared:  # đường dẫn do người dùng khai báo mà thiếu file thì báo; đường dẫn mặc định thì im lặng
        for m in c.dict_missing:
            c.warnings.append(f"Không đọc được file từ điển: {m}")

    mn = data["manual"]
    c.manual_tokenizer = str(mn["tokenizer"])
    c.block_tokens = int(mn["block_tokens"])
    c.block_max_items = int(mn["block_max_items"])
    if c.block_tokens < 200 or c.block_max_items < 1:
        raise ValueError("manual.block_tokens phải >= 200 và manual.block_max_items >= 1.")
    set_manual = user_data.get("manual", {})
    c.manual_instruction = read_text_setting(
        mn.get("instruction_file"), base_dir, DEFAULT_MANUAL_INSTRUCTION, c.warnings, "manual.instruction_file",
        warn="instruction_file" in set_manual,
    )

    b = data["batch"]
    c.recursive = bool(b["recursive"])
    c.continue_on_error = bool(b["continue_on_error"])
    c.refresh()
    return c
