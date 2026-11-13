"""Mô hình dữ liệu của hộp thoại Cài đặt: danh sách mục, đọc/ghi giá trị vào Config, và phần ghi ra config.local.toml.

Không phụ thuộc tkinter nên test được. `values` luôn là dict {key: giá trị Python đã kiểm tra}.
"""
import re
from dataclasses import dataclass

from .. import config as cfgmod

TAB_ORDER = ("Mô hình", "Dịch", "Đầu ra", "Từ điển", "Chat thủ công")


@dataclass(frozen=True)
class Field:
    key: str
    tab: str
    label: str
    kind: str  # str | esc | path | int | optint | float | bool | choice | regex
    path: tuple  # vị trí trong config.toml
    attr: str  # thuộc tính trên Config; "a.b" = cfg.a["b"]
    choices: tuple = ()
    help: str = ""
    minimum: float = None
    group: str = ""


def _f(*a, **k):
    return Field(*a, **k)


FIELDS = [
    _f("backend", "Mô hình", "Cách chạy model", "choice", ("backend", "type"), "backend", choices=("ollama", "llama_cpp"),
       help="ollama: gọi Ollama đang chạy. llama_cpp: nạp file .gguf ngay trong app.", group="Chung"),
    _f("host", "Mô hình", "Ollama host", "str", ("ollama", "host"), "host", group="Ollama"),
    _f("ollama_model", "Mô hình", "Model Ollama", "str", ("ollama", "model"), "ollama_model", group="Ollama"),
    _f("timeout", "Mô hình", "Timeout mỗi yêu cầu (giây)", "float", ("ollama", "timeout"), "timeout", minimum=1, group="Ollama"),
    _f("retries", "Mô hình", "Số lần thử lại khi lỗi", "int", ("ollama", "retries"), "retries", minimum=0, group="Ollama"),
    _f("keep_alive", "Mô hình", "Giữ model trong RAM", "str", ("ollama", "keep_alive"), "keep_alive",
       help="vd. 30m. Bỏ trống = mặc định của Ollama.", group="Ollama"),
    _f("o_ctx", "Mô hình", "num_ctx (độ dài ngữ cảnh)", "optint", ("ollama", "options", "num_ctx"), "ollama_options.num_ctx",
       minimum=256, help="Thấp hơn = nhanh hơn. 1024-2048 đủ cho ô Excel ngắn.", group="Ollama"),
    _f("o_temp", "Mô hình", "temperature", "float", ("ollama", "options", "temperature"), "ollama_options.temperature",
       minimum=0, group="Ollama"),
    _f("o_threads", "Mô hình", "num_thread (luồng CPU)", "optint", ("ollama", "options", "num_thread"),
       "ollama_options.num_thread", minimum=1, help="Thử bằng số nhân vật lý (i5-8500: 6). Bỏ trống = tự chọn.", group="Ollama"),
    _f("model_path", "Mô hình", "File model .gguf", "path", ("llama_cpp", "model_path"), "model_path", group="llama.cpp"),
    _f("l_ctx", "Mô hình", "n_ctx", "int", ("llama_cpp", "n_ctx"), "n_ctx", minimum=256, group="llama.cpp"),
    _f("l_threads", "Mô hình", "n_threads (0 = tự chọn)", "int", ("llama_cpp", "n_threads"), "n_threads", minimum=0, group="llama.cpp"),
    _f("l_gpu", "Mô hình", "n_gpu_layers", "int", ("llama_cpp", "n_gpu_layers"), "n_gpu_layers", minimum=0, group="llama.cpp"),

    _f("mode", "Dịch", "Kiểu ghi", "choice", ("translate", "mode"), "mode", choices=("replace", "bilingual"),
       help="replace: thay bằng bản dịch. bilingual: giữ cả tiếng Nhật và tiếng Anh.", group="Kiểu ghi"),
    _f("cell_sep", "Dịch", "Ngăn cách JP/EN trong ô (song ngữ)", "esc", ("translate", "bilingual_cell_sep"), "cell_sep",
       help=r"Dùng \n cho xuống dòng.", group="Kiểu ghi"),
    _f("shape_sep", "Dịch", "Ngăn cách JP/EN trong shape (song ngữ)", "esc", ("translate", "bilingual_shape_sep"), "shape_sep",
       group="Kiểu ghi"),
    _f("t_cells", "Dịch", "Ô trong sheet (và tiêu đề Table)", "bool", ("targets", "cells"), "targets.cells", group="Dịch phần nào"),
    _f("t_shapes", "Dịch", "Text box / shape", "bool", ("targets", "shapes"), "targets.shapes", group="Dịch phần nào"),
    _f("t_charts", "Dịch", "Biểu đồ", "bool", ("targets", "charts"), "targets.charts", group="Dịch phần nào"),
    _f("t_diagrams", "Dịch", "SmartArt", "bool", ("targets", "diagrams"), "targets.diagrams", group="Dịch phần nào"),
    _f("t_comments", "Dịch", "Comment / ghi chú", "bool", ("targets", "comments"), "targets.comments", group="Dịch phần nào"),
    _f("src", "Dịch", "Regex nhận diện chữ cần dịch", "regex", ("translate", "source_pattern"), "src_re",
       help="Mặc định: có ký tự Nhật (hiragana, katakana, kanji).", group="Nâng cao"),

    _f("suffix", "Đầu ra", "Hậu tố tên file/folder kết quả", "str", ("output", "suffix"), "suffix", group="Tên"),
    _f("md", "Đầu ra", "Xuất thêm file Markdown", "bool", ("output", "markdown"), "md", group="Markdown"),
    _f("md_suffix", "Đầu ra", "Hậu tố folder Markdown", "str", ("output", "markdown_suffix"), "md_suffix", group="Markdown"),
    _f("md_rows", "Đầu ra", "Số dòng tối đa mỗi sheet trong .md", "int", ("output", "markdown_max_rows"), "md_max_rows",
       minimum=1, group="Markdown"),
    _f("md_cols", "Đầu ra", "Số cột tối đa mỗi sheet trong .md", "int", ("output", "markdown_max_cols"), "md_max_cols",
       minimum=1, group="Markdown"),
    _f("cache", "Đầu ra", "Lưu cache bản dịch (chạy lại / tiếp tục không phải dịch lại)", "bool", ("output", "cache"), "cache",
       group="Khác"),
    _f("recursive", "Đầu ra", "Dịch cả thư mục con khi chọn folder", "bool", ("batch", "recursive"), "recursive", group="Folder"),
    _f("cont", "Đầu ra", "File lỗi thì bỏ qua và dịch tiếp file khác", "bool", ("batch", "continue_on_error"),
       "continue_on_error", group="Folder"),
    _f("h_on", "Đầu ra", "Ghi lịch sử dịch (model, token, tok/s)", "bool", ("history", "enabled"), "history_enabled",
       help="Chỉ lưu số liệu, không lưu nội dung file.", group="Lịch sử"),
    _f("h_max", "Đầu ra", "Số dòng lịch sử tối đa", "int", ("history", "max_entries"), "history_max", minimum=10, group="Lịch sử"),

    _f("d_on", "Từ điển", "Dùng từ điển giữ nguyên tiếng Nhật", "bool", ("dictionary", "enabled"), "dict_enabled", group="Từ điển"),
    _f("d_suggest", "Từ điển", "Gợi ý danh từ riêng chưa có trong từ điển khi dịch", "bool", ("dictionary", "suggest"),
       "suggest", group="Từ điển"),
    _f("d_max", "Từ điển", "Số gợi ý tối đa mỗi lần hỏi", "int", ("dictionary", "suggest_max"), "suggest_max", minimum=1,
       group="Từ điển"),

    _f("m_tok", "Chat thủ công", "Bộ đếm token", "choice", ("manual", "tokenizer"), "manual_tokenizer",
       choices=("o200k_base", "cl100k_base", "estimate"), help="estimate: không dùng tiktoken, ước lượng thiên về dư.",
       group="Chia khối"),
    _f("m_block", "Chat thủ công", "Token tối đa mỗi khối", "int", ("manual", "block_tokens"), "block_tokens", minimum=200,
       help="Kết quả chat cũng dài cỡ khối gửi đi; nhiều chat giới hạn độ dài câu trả lời.", group="Chia khối"),
    _f("m_items", "Chat thủ công", "Số mục tối đa mỗi khối", "int", ("manual", "block_max_items"), "block_max_items",
       minimum=1, group="Chia khối"),
]
BY_KEY = {f.key: f for f in FIELDS}


def fields_of(tab):
    return [f for f in FIELDS if f.tab == tab]


# ---- đọc / ghi thuộc tính của Config
def _get(cfg, attr):
    if "." in attr:
        name, key = attr.split(".", 1)
        return getattr(cfg, name).get(key)
    v = getattr(cfg, attr)
    return v.pattern if attr == "src_re" else v


def _set(cfg, attr, value):
    if "." in attr:
        name, key = attr.split(".", 1)
        d = getattr(cfg, name)
        if value is None:
            d.pop(key, None)
        else:
            d[key] = value
    elif attr == "src_re":
        setattr(cfg, attr, re.compile(value))
    else:
        setattr(cfg, attr, value)


def read_values(cfg):
    out = {}
    for f in FIELDS:
        v = _get(cfg, f.attr)
        out[f.key] = str(v) if f.kind == "path" and v is not None else v
    return out


def to_text(f, value):
    """Giá trị -> chuỗi hiển thị trong ô nhập."""
    if value is None:
        return ""
    if f.kind == "esc":
        return str(value).replace("\\", "\\\\").replace("\n", "\\n")
    if f.kind == "float":
        return f"{value:g}"
    return str(value)


def parse_value(f, text):
    """Chuỗi trong ô nhập -> giá trị Python; ném ValueError(thông báo cho người dùng) nếu sai."""
    if f.kind == "esc":
        return re.sub(r"\\(n|\\)", lambda m: "\n" if m.group(1) == "n" else "\\", text)
    t = text.strip()
    if f.kind == "regex":
        if not t:
            raise ValueError(f"{f.label}: không được để trống")
        try:
            re.compile(t)
        except re.error as e:
            raise ValueError(f"{f.label}: regex không hợp lệ ({e})") from None
        return t
    if f.kind not in ("int", "optint", "float"):
        return t
    if f.kind == "optint" and not t:
        return None
    try:
        v = float(t) if f.kind == "float" else int(t)
    except ValueError:
        raise ValueError(f"{f.label}: cần một số hợp lệ") from None
    if f.minimum is not None and v < f.minimum:
        raise ValueError(f"{f.label}: tối thiểu {f.minimum:g}")
    return v


def apply_values(cfg, values):
    """Ghi `values` vào cfg (đối tượng Config, thường là bản copy), rồi tính lại model/options và table_headers."""
    for f in FIELDS:
        if f.key in values:
            _set(cfg, f.attr, values[f.key])
    cfg.targets["table_headers"] = cfg.targets["cells"]  # tên cột Table phải đi cùng ô tiêu đề
    if "model_path" in values and values["model_path"] is not None:
        from pathlib import Path

        cfg.model_path = Path(str(values["model_path"])).expanduser()
    cfg.refresh()
    cfg.reload_dictionary()
    return cfg


def overrides(initial, new):
    """Dict lồng nhau (đúng cấu trúc config.toml) chỉ gồm các mục người dùng đã đổi; None = xóa khỏi file riêng."""
    out = {}
    for f in FIELDS:
        if f.key in new and new[f.key] != initial.get(f.key):
            node = out
            for part in f.path[:-1]:
                node = node.setdefault(part, {})
            node[f.path[-1]] = new[f.key]
    if "cells" in out.get("targets", {}):
        out["targets"]["table_headers"] = out["targets"]["cells"]  # luôn đi cùng nhau
    return out


def defaults():
    """Giá trị mặc định của mọi mục (từ DEFAULT_CONFIG), cùng dạng với read_values."""
    out = {}
    for f in FIELDS:
        node = cfgmod.DEFAULT_CONFIG
        for part in f.path:
            node = node.get(part) if isinstance(node, dict) else None
        if f.kind == "esc" and node is None:
            node = ""
        out[f.key] = node
    return out
