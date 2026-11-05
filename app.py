#!/usr/bin/env python3
"""Dịch Excel JP -> EN bằng model local qua Ollama, sửa trực tiếp XML trong file .xlsx.

Khác bản dùng openpyxl: không mở/ghi lại workbook nên GIỮ NGUYÊN shape, text box,
biểu đồ, hình, định dạng, công thức, macro... Chỉ các đoạn chữ tiếng Nhật bị thay.

Dịch được (bật/tắt từng phần trong config.toml, mục [targets]):
  - Chữ trong cell (shared strings + inline strings)
  - Text trong shape / text box / WordArt (xl/drawings)
  - Tiêu đề, nhãn trong biểu đồ (xl/charts) và SmartArt (xl/diagrams)
  - Comment/note kiểu cũ (xl/comments)
  - Tên cột của Table (để khớp với header cell đã dịch)

Không đụng: công thức, tên sheet, pivot cache, threaded comments.

Ngoài ra xuất 1 file Markdown (.md) chung: mỗi sheet một mục, giữ NGUYÊN tên sheet gốc
và số dòng / chữ cột của Excel để đối chiếu.

Cấu hình: config.toml (+ config.local.toml) cạnh app.py; prompt nằm trong prompts/.

Chạy GUI:  python app.py
Chạy CLI:  python app.py input.xlsx [-o output.xlsx] [-c config.toml] [-m qwen2.5:7b]
                                    [--host URL] [--mode replace|bilingual] [--no-md]
"""
import argparse
import copy
import datetime
import hashlib
import json
import posixpath
import re
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path

try:
    from lxml import etree
except ImportError:  # pragma: no cover
    sys.exit("Thiếu thư viện lxml. Cài bằng:  pip install lxml")

try:
    import tomllib
except ImportError:  # Python < 3.11
    try:
        import tomli as tomllib
    except ImportError:  # pragma: no cover
        sys.exit("Python < 3.11 cần thư viện tomli. Cài bằng:  pip install tomli")

APP_DIR = Path(__file__).resolve().parent

NS_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
M = "{%s}" % NS_M
A = "{%s}" % NS_A
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
NSMAP = {"m": NS_M, "a": NS_A}

RE_SHARED = re.compile(r"^xl/sharedStrings\.xml$")
RE_SHEET = re.compile(r"^xl/worksheets/[^/]+\.xml$")
RE_COMMENTS = re.compile(r"^xl/comments(/[^/]*|[^/]*)\.xml$")
RE_DRAWML = re.compile(r"^xl/(drawings/drawing|charts/chart|diagrams/data)[^/]*\.xml$")
RE_TABLE = re.compile(r"^xl/tables/table[^/]*\.xml$")


# ---------------------------------------------------------------- Cấu hình
# Giá trị mặc định (dùng khi không có config.toml hoặc thiếu mục). Ý nghĩa từng mục: xem config.toml.
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

DEFAULT_CONFIG = {
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
        "markdown_max_rows": 20000,
        "markdown_max_cols": 200,
        "cache": True,
    },
}


class Config:
    """Cấu hình đã nạp. Có thể copy.copy() rồi đổi thuộc tính (GUI / tham số dòng lệnh làm vậy)."""

    def signature(self):
        """Dấu vân tay của những thứ ảnh hưởng tới bản dịch; đổi thì cache cũ không dùng lại."""
        blob = json.dumps(
            [self.model, self.system_prompt, self.user_template, self.options],
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _deep_merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _read_text_setting(rel, base_dir, default, warnings, label, warn=True):
    if not rel:
        return default
    p = Path(str(rel)).expanduser()
    if not p.is_absolute():
        p = base_dir / p
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        if warn:  # đường dẫn mặc định (không do config khai báo) thiếu file thì lặng lẽ dùng prompt trong code
            warnings.append(f"Không đọc được {label} ({p}) — dùng prompt mặc định trong app.py.")
        return default
    return text or default


def load_config(path=None):
    """Nạp config. path=None: config.toml rồi config.local.toml cạnh app.py (nếu có)."""
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
            _deep_merge(data, copy.deepcopy(loaded))
            _deep_merge(user_data, loaded)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"Không đọc được {f}: {e}") from e
    base_dir = files[-1].parent if files else APP_DIR

    c = Config()
    c.source_files = [str(f) for f in files]
    c.warnings = []

    o = data["ollama"]
    c.host = str(o["host"]).rstrip("/")
    c.model = str(o["model"])
    c.keep_alive = str(o.get("keep_alive", "") or "")
    c.timeout = float(o["timeout"])
    c.retries = int(o["retries"])
    c.options = dict(o.get("options") or {})

    pr = data["prompt"]
    set_by_user = user_data.get("prompt", {})
    c.system_prompt = _read_text_setting(
        pr.get("system_file"), base_dir, DEFAULT_SYSTEM_PROMPT, c.warnings, "prompt.system_file",
        warn="system_file" in set_by_user,
    )
    c.user_template = _read_text_setting(
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

    out = data["output"]
    c.suffix = str(out["suffix"])
    c.md = bool(out["markdown"])
    c.md_max_rows = int(out["markdown_max_rows"])
    c.md_max_cols = int(out["markdown_max_cols"])
    c.cache = bool(out["cache"])
    return c


# ---------------------------------------------------------------- Ollama
def _http_json(url, payload=None, timeout=600):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_models(host):
    try:
        info = _http_json(f"{host}/api/tags", timeout=5)
        return [m["name"] for m in info.get("models", [])]
    except Exception:
        return []


def build_messages(text, cfg):
    tpl = cfg.user_template
    user = tpl.replace("{text}", text) if "{text}" in tpl else f"{tpl}\n\n{text}"
    msgs = []
    if cfg.system_prompt:
        msgs.append({"role": "system", "content": cfg.system_prompt})
    msgs.append({"role": "user", "content": user})
    return msgs


def translate_text(text, cfg):
    payload = {
        "model": cfg.model,
        "stream": False,
        "options": dict(cfg.options),
        "messages": build_messages(text, cfg),
    }
    if cfg.keep_alive:
        payload["keep_alive"] = cfg.keep_alive
    last_err = None
    for _ in range(cfg.retries + 1):
        try:
            res = _http_json(f"{cfg.host}/api/chat", payload, timeout=cfg.timeout)
            out = res["message"]["content"].strip()
            if out:
                return out
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"Ollama lỗi: {last_err}")


# ---------------------------------------------------------------- XML helpers
def _parse(data):
    parser = etree.XMLParser(huge_tree=True, resolve_entities=False)
    return etree.fromstring(data, parser)


def _serialize(root):
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _set_runs(ts, new):
    """Đặt toàn bộ bản dịch vào run đầu tiên, làm rỗng các run còn lại."""
    ts[0].text = new
    ts[0].set(XML_SPACE, "preserve")
    for t in ts[1:]:
        t.text = ""


def _collect_sml(conts, units, rx, sep):
    """conts: các phần tử <si>, <is>, <text> của SpreadsheetML (có thể có rich runs)."""
    for cont in conts:
        ts = cont.xpath(".//m:t[not(ancestor::m:rPh)]", namespaces=NSMAP)
        if not ts:
            continue
        text = "".join(t.text or "" for t in ts)
        if not rx.search(text):
            continue

        def setter(new, cont=cont, ts=ts):
            _set_runs(ts, new)
            # furigana cũ không còn đúng nữa
            for e in cont.xpath("./m:rPh|./m:phoneticPr", namespaces=NSMAP):
                cont.remove(e)

        units.append((text, sep, setter))


def _collect_drawingml(root, units, rx, sep):
    """Mỗi đoạn <a:p> là một đơn vị dịch (text box, shape, tiêu đề chart...)."""
    for p in root.iter(A + "p"):
        ts = [r.find(A + "t") for r in p.findall(A + "r")]
        ts = [t for t in ts if t is not None]
        if not ts:
            continue
        text = "".join(t.text or "" for t in ts)
        if not rx.search(text):
            continue

        def setter(new, ts=ts):
            _set_runs(ts, new)

        units.append((text, sep, setter))


def _collect_table(root, tables_post, units, rx, sep):
    cols = root.xpath("//m:tableColumn", namespaces=NSMAP)
    if not cols:
        return
    for c in cols:
        raw = c.get("name", "")
        text = raw.replace("_x000a_", "\n")
        if not rx.search(text):
            continue

        def setter(new, c=c):
            c.set("name", new.replace("\n", "_x000a_"))

        units.append((text, sep, setter))
    tables_post.append(cols)


def _dedupe_table_names(cols_list):
    for cols in cols_list:
        seen = set()
        for c in cols:
            n = base = c.get("name", "")
            k = 2
            while n.lower() in seen:
                n = f"{base}{k}"
                k += 1
            if n != base:
                c.set("name", n)
            seen.add(n.lower())


# ---------------------------------------------------------------- Markdown export
NS_XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def _md_fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime.datetime):
        return v.date().isoformat() if v.time() == datetime.time(0) else v.isoformat(" ")
    if isinstance(v, (datetime.date, datetime.time)):
        return v.isoformat()
    return str(v)


def _md_cell(v):
    s = _md_fmt(v).strip().replace("|", "\\|")
    return s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _resolve(base_dir, target):
    if target.startswith("/"):
        return target[1:]
    return posixpath.normpath(posixpath.join(base_dir, target))


def _sheet_textboxes(zf):
    """{tên sheet: [(vị trí gần ô, text), ...]} lấy từ drawings của từng sheet."""
    from openpyxl.utils import get_column_letter

    out = {}
    try:
        wb = _parse(zf.read("xl/workbook.xml"))
        rels = _parse(zf.read("xl/_rels/workbook.xml.rels"))
        rid2t = {r.get("Id"): r.get("Target") for r in rels}
        names = set(zf.namelist())
        for sh in wb.xpath("//m:sheets/m:sheet", namespaces=NSMAP):
            name = sh.get("name")
            tgt = rid2t.get(sh.get("{%s}id" % NS_R))
            if not tgt:
                continue
            spath = _resolve("xl", tgt)
            relp = posixpath.join(posixpath.dirname(spath), "_rels", posixpath.basename(spath) + ".rels")
            if relp not in names:
                continue
            for rel in _parse(zf.read(relp)):
                if not rel.get("Type", "").endswith("/drawing"):
                    continue
                dpath = _resolve(posixpath.dirname(spath), rel.get("Target"))
                if dpath not in names:
                    continue
                droot = _parse(zf.read(dpath))
                for anchor in droot:
                    if not etree.QName(anchor).localname.endswith("Anchor"):
                        continue
                    paras = []
                    for p in anchor.xpath(
                        ".//a:p[not(ancestor::mc:Fallback)]",
                        namespaces={"a": NS_A, "mc": NS_MC},
                    ):
                        t = "".join(x.text or "" for x in p.iter(A + "t")).strip()
                        if t:
                            paras.append(t)
                    if not paras:
                        continue
                    pos = ""
                    fr = anchor.find("{%s}from" % NS_XDR)
                    if fr is not None:
                        try:
                            col = int(fr.find("{%s}col" % NS_XDR).text)
                            row = int(fr.find("{%s}row" % NS_XDR).text)
                            pos = f"{get_column_letter(col + 1)}{row + 1}"
                        except Exception:
                            pass
                    out.setdefault(name, []).append((pos, "\n".join(paras)))
    except Exception:
        pass
    return out


def export_markdown(
    xlsx_path, md_path, gloss=lambda name: None, log=print, max_rows=20000, max_cols=200
):
    """Xuất toàn bộ workbook (đã dịch) ra 1 file Markdown, mỗi sheet một mục."""
    try:
        import openpyxl
        from openpyxl.utils import get_column_letter
    except ImportError:
        log("Bỏ qua xuất Markdown: thiếu openpyxl (pip install openpyxl).")
        return None

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # openpyxl cảnh báo shape khi đọc; file gốc không bị ảnh hưởng
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    with zipfile.ZipFile(xlsx_path) as zf:
        boxes = _sheet_textboxes(zf)

    sections, toc = [], []
    for idx, ws in enumerate(wb.worksheets, 1):
        rows, comments = [], []
        max_col = 0
        truncated = False
        for row in ws.iter_rows(max_col=min(ws.max_column or 1, max_cols)):
            if not row:
                continue
            r = row[0].row
            if r > max_rows:
                truncated = True
                break
            vals = [c.value for c in row]
            for c in row:
                if c.comment and c.comment.text:
                    comments.append((c.coordinate, c.comment.text.strip()))
            last = max((i + 1 for i, v in enumerate(vals) if _md_fmt(v).strip() != ""), default=0)
            if last:
                rows.append((r, vals))
                max_col = max(max_col, last)

        en = gloss(ws.title)
        state = "" if ws.sheet_state == "visible" else f" *(sheet {ws.sheet_state})*"
        title = f"{idx}. `{ws.title}`" + (f" — {en}" if en else "")
        dim = ws.dimensions if rows else "(trống)"
        toc.append(f"- {title} — vùng dữ liệu `{dim}`{state}")

        lines = [f"## Sheet {idx}: `{ws.title}`" + (f" — {en}" if en else "") + state, ""]
        lines.append(f"Tên sheet trong Excel: `{ws.title}` · vùng dữ liệu: `{dim}`")
        lines.append("")
        if rows:
            hdr = "| # | " + " | ".join(get_column_letter(i + 1) for i in range(max_col)) + " |"
            sep = "|---:|" + "|".join("---" for _ in range(max_col)) + "|"
            lines += [hdr, sep]
            for r, vals in rows:
                cells = [_md_cell(v) for v in vals[:max_col]] + [""] * (max_col - len(vals[:max_col]))
                lines.append(f"| {r} | " + " | ".join(cells) + " |")
            lines.append("")
            if truncated:
                lines.append(f"*(đã cắt ở dòng {max_rows})*\n")
        if comments:
            lines += ["**Comments**", ""]
            lines += [f"- `{ref}`: {t.replace(chr(10), ' ')}" for ref, t in comments]
            lines.append("")
        if boxes.get(ws.title):
            lines += ["**Text box / shape**", ""]
            for pos, t in boxes[ws.title]:
                lines.append(f"- gần `{pos}`: " + t.replace("\n", " / ") if pos else "- " + t.replace("\n", " / "))
            lines.append("")
        sections.append("\n".join(lines))

    head = [
        f"# {Path(xlsx_path).name}",
        "",
        "> Cột `#` = số dòng Excel, tiêu đề cột = chữ cột Excel (A, B, C…). "
        "Dòng trống được bỏ qua nhưng số dòng giữ nguyên. Tên sheet là tên gốc trong file Excel.",
        "",
        "## Danh sách sheet",
        "",
        *toc,
        "",
    ]
    Path(md_path).write_text("\n".join(head) + "\n" + "\n".join(sections), encoding="utf-8")
    return md_path


# ---------------------------------------------------------------- Main
def default_out(in_path, cfg):
    p = Path(in_path)
    return str(p.with_name(f"{p.stem}{cfg.suffix}{p.suffix}"))


def process_xlsx(
    in_path,
    out_path,
    cfg,
    log=print,
    progress=lambda done, total: None,
    should_stop=lambda: False,
):
    in_path, out_path = Path(in_path), Path(out_path)
    if in_path.resolve() == out_path.resolve():
        raise ValueError("File output phải khác file input (kiểm tra output.suffix trong config).")
    if in_path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError("Chỉ hỗ trợ .xlsx / .xlsm (file .xls cũ hãy Save As .xlsx trước).")

    for w in cfg.warnings:
        log(f"Cảnh báo: {w}")
    log(
        f"Cấu hình: {', '.join(cfg.source_files) or 'mặc định'} · model {cfg.model} · "
        f"chế độ {cfg.mode}"
    )

    tg = cfg.targets
    rx = cfg.src_re
    units = []  # (text, sep, setter)
    parsed = {}  # tên part -> root đã parse
    tables_post = []

    with zipfile.ZipFile(in_path) as zin:
        infos = zin.infolist()
        for info in infos:
            n = info.filename
            root = None
            before = len(units)
            if RE_SHARED.match(n):
                if not tg["cells"]:
                    continue
                root = _parse(zin.read(n))
                _collect_sml(root.xpath("//m:si", namespaces=NSMAP), units, rx, cfg.cell_sep)
            elif RE_COMMENTS.match(n):
                if not tg["comments"]:
                    continue
                root = _parse(zin.read(n))
                _collect_sml(
                    root.xpath("//m:comment/m:text", namespaces=NSMAP), units, rx, cfg.cell_sep
                )
            elif RE_SHEET.match(n):
                if not tg["cells"]:
                    continue
                data = zin.read(n)
                if b"inlineStr" not in data:
                    continue
                root = _parse(data)
                _collect_sml(
                    root.xpath("//m:c[@t='inlineStr']/m:is", namespaces=NSMAP),
                    units, rx, cfg.cell_sep,
                )
            elif RE_DRAWML.match(n):
                kind = (
                    "shapes" if n.startswith("xl/drawings/")
                    else "charts" if n.startswith("xl/charts/")
                    else "diagrams"
                )
                if not tg[kind]:
                    continue
                root = _parse(zin.read(n))
                _collect_drawingml(root, units, rx, cfg.shape_sep)
            elif RE_TABLE.match(n):
                if not tg["table_headers"]:
                    continue
                root = _parse(zin.read(n))
                _collect_table(root, tables_post, units, rx, cfg.cell_sep)
            if root is not None and len(units) > before:
                parsed[n] = root  # chỉ ghi lại part có đoạn cần dịch

        unique = list(dict.fromkeys(u[0] for u in units))
        log(f"Tìm thấy {len(units)} đoạn chữ cần dịch ({len(unique)} chuỗi khác nhau).")

        # Cache dịch (ghi ra đĩa để chạy lại/tiếp tục không phải dịch lại).
        # Chỉ dùng lại khi model, prompt và options không đổi.
        sig = cfg.signature()
        cache_path = Path(str(out_path) + ".cache.json")
        mapping = {}
        if cfg.cache:
            try:
                c = json.loads(cache_path.read_text(encoding="utf-8"))
                if c.get("sig") == sig:
                    mapping = c.get("map", {})
            except Exception:
                pass

        def save_cache():
            if not cfg.cache:
                return
            try:
                cache_path.write_text(
                    json.dumps({"sig": sig, "model": cfg.model, "map": mapping}, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass

        todo = [t for t in unique if t not in mapping]
        if len(todo) < len(unique):
            log(f"Dùng lại {len(unique) - len(todo)} bản dịch từ cache.")
        total = len(todo)
        progress(0, total)
        errors = 0
        for i, text in enumerate(todo, 1):
            if should_stop():
                log("Đã dừng — lưu phần đã dịch.")
                break
            try:
                mapping[text] = translate_text(text, cfg)
            except Exception as e:  # noqa: BLE001
                errors += 1
                log(f"Lỗi với đoạn «{text[:30]}…»: {e}")
            progress(i, total)
            if i % 10 == 0:
                log(f"  {i}/{total}")
                save_cache()
        save_cache()

        # Áp bản dịch vào XML
        applied = 0
        for text, sep, setter in units:
            en = mapping.get(text)
            if not en:
                continue
            setter(en if cfg.mode == "replace" else f"{text}{sep}{en}")
            applied += 1
        _dedupe_table_names(tables_post)

        # Ghi file mới: copy nguyên mọi part, chỉ thay các part đã sửa
        with zipfile.ZipFile(out_path, "w") as zout:
            for info in infos:
                data = (
                    _serialize(parsed[info.filename])
                    if info.filename in parsed
                    else zin.read(info.filename)
                )
                zout.writestr(info, data, compress_type=info.compress_type)

    log(f"Xong: đã dịch {applied}/{len(units)} đoạn, {errors} lỗi. Đã lưu: {out_path}")

    if cfg.md:
        def gloss(name):  # bản dịch tên sheet, chỉ để tham khảo trong .md (Excel giữ tên gốc)
            if not rx.search(name):
                return None
            if name not in mapping:
                try:
                    mapping[name] = translate_text(name, cfg)
                except Exception:
                    return None
            return mapping[name]

        try:
            md_path = export_markdown(
                out_path, out_path.with_suffix(".md"), gloss, log,
                max_rows=cfg.md_max_rows, max_cols=cfg.md_max_cols,
            )
            if md_path:
                save_cache()
                log(f"Đã xuất Markdown: {md_path}")
        except Exception as e:  # noqa: BLE001
            log(f"Không xuất được Markdown: {e}")
    return applied, errors


# ---------------------------------------------------------------- GUI
def run_gui(cfg):
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title("Excel JP → EN (Ollama)")
    root.geometry("660x540")

    file_var = tk.StringVar()
    host_var = tk.StringVar(value=cfg.host)
    model_var = tk.StringVar(value=cfg.model)
    mode_var = tk.StringVar(value=cfg.mode)
    md_var = tk.BooleanVar(value=cfg.md)
    stop_flag = {"stop": False}

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    def browse():
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xlsm"), ("All", "*.*")])
        if p:
            file_var.set(p)

    ttk.Label(frm, text="File Excel:").grid(row=0, column=0, sticky="w")
    ttk.Entry(frm, textvariable=file_var, width=55).grid(row=0, column=1, sticky="ew")
    ttk.Button(frm, text="Chọn…", command=browse).grid(row=0, column=2, padx=4)

    ttk.Label(frm, text="Ollama host:").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=host_var).grid(row=1, column=1, sticky="ew")

    ttk.Label(frm, text="Model:").grid(row=2, column=0, sticky="w")
    model_box = ttk.Combobox(frm, textvariable=model_var, values=[cfg.model])
    model_box.grid(row=2, column=1, sticky="ew")

    def refresh_models():
        ms = list_models(host_var.get().rstrip("/"))
        if ms:
            model_box["values"] = ms
            if model_var.get() not in ms:
                model_var.set(ms[0])
        else:
            messagebox.showwarning(
                "Ollama", "Không kết nối được Ollama. Đã chạy `ollama serve` chưa?"
            )

    ttk.Button(frm, text="Tải model", command=refresh_models).grid(row=2, column=2, padx=4)

    ttk.Label(frm, text="Kiểu ghi:").grid(row=3, column=0, sticky="w", pady=4)
    mf = ttk.Frame(frm)
    mf.grid(row=3, column=1, sticky="w")
    ttk.Radiobutton(mf, text="Thay bằng bản dịch", variable=mode_var, value="replace").pack(side="left")
    ttk.Radiobutton(mf, text="Song ngữ (JP + EN)", variable=mode_var, value="bilingual").pack(side="left", padx=10)
    ttk.Checkbutton(mf, text="Xuất thêm .md", variable=md_var).pack(side="left", padx=10)

    pbar = ttk.Progressbar(frm, mode="determinate")
    pbar.grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)

    logbox = scrolledtext.ScrolledText(frm, height=16, state="disabled")
    logbox.grid(row=5, column=0, columnspan=3, sticky="nsew")
    frm.columnconfigure(1, weight=1)
    frm.rowconfigure(5, weight=1)

    def log(msg):
        def _do():
            logbox.configure(state="normal")
            logbox.insert("end", msg + "\n")
            logbox.see("end")
            logbox.configure(state="disabled")

        root.after(0, _do)

    def progress(done, total):
        def _do():
            pbar["maximum"] = max(total, 1)
            pbar["value"] = done

        root.after(0, _do)

    btns = ttk.Frame(frm)
    btns.grid(row=6, column=0, columnspan=3, pady=8)
    start_btn = ttk.Button(btns, text="Bắt đầu dịch")
    stop_btn = ttk.Button(btns, text="Dừng", state="disabled")
    start_btn.pack(side="left", padx=4)
    stop_btn.pack(side="left", padx=4)

    def worker(src):
        try:
            c = copy.copy(cfg)  # giá trị trên giao diện ghi đè config
            c.host = host_var.get().rstrip("/")
            c.model = model_var.get()
            c.mode = mode_var.get()
            c.md = md_var.get()
            process_xlsx(
                src,
                default_out(src, c),
                c,
                log=log,
                progress=progress,
                should_stop=lambda: stop_flag["stop"],
            )
        except Exception as e:  # noqa: BLE001
            log(f"LỖI: {e}")
        finally:
            root.after(
                0,
                lambda: (start_btn.config(state="normal"), stop_btn.config(state="disabled")),
            )

    def start():
        src = file_var.get()
        if not src or not Path(src).exists():
            messagebox.showerror("Lỗi", "Chọn file Excel trước.")
            return
        stop_flag["stop"] = False
        start_btn.config(state="disabled")
        stop_btn.config(state="normal")
        threading.Thread(target=worker, args=(src,), daemon=True).start()

    start_btn.config(command=start)
    stop_btn.config(command=lambda: stop_flag.update(stop=True))
    root.after(200, lambda: model_box.__setitem__("values", list_models(cfg.host) or [cfg.model]))
    root.mainloop()


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description="Dịch Excel JP→EN bằng Ollama (sửa XML trực tiếp)")
    ap.add_argument("input", nargs="?", help="file .xlsx/.xlsm (bỏ trống để mở giao diện)")
    ap.add_argument("-c", "--config", help="đường dẫn file cấu hình .toml (mặc định: config.toml cạnh app.py)")
    ap.add_argument("-o", "--output", help="file kết quả (mặc định: <tên><output.suffix>.xlsx)")
    ap.add_argument("-m", "--model", help="ghi đè ollama.model")
    ap.add_argument("--host", help="ghi đè ollama.host")
    ap.add_argument("--mode", choices=["replace", "bilingual"], help="ghi đè translate.mode")
    ap.add_argument("--no-md", action="store_true", help="không xuất file Markdown")
    a = ap.parse_args()

    try:
        cfg = load_config(a.config)
    except (OSError, ValueError) as e:
        sys.exit(f"Lỗi cấu hình: {e}")
    if a.model:
        cfg.model = a.model
    if a.host:
        cfg.host = a.host.rstrip("/")
    if a.mode:
        cfg.mode = a.mode
    if a.no_md:
        cfg.md = False

    if not a.input:
        return run_gui(cfg)
    process_xlsx(a.input, a.output or default_out(a.input, cfg), cfg)


if __name__ == "__main__":
    main()
