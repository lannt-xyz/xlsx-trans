"""Dòng lệnh. Bỏ trống đầu vào để mở giao diện."""
import argparse
import sys
import zipfile
from pathlib import Path

from . import batch, dictionary, gui, pipeline
from .config import BACKENDS, load_config


def parse_selection(text, n):
    """'1,3-5' -> {1,3,4,5}; 'a'/'all' -> tất cả; chỉ giữ số trong 1..n. Ném ValueError nếu sai cú pháp."""
    text = text.strip().lower()
    if text in ("a", "all"):
        return set(range(1, n + 1))
    picked = set()
    for part in filter(None, (p.strip() for p in text.split(","))):
        lo, _, hi = part.partition("-")
        a, b = int(lo), int(hi or lo)
        picked.update(range(min(a, b), max(a, b) + 1))
    return {i for i in picked if 1 <= i <= n}


def cli_review(cands, ask=input, out=print, interactive=None):
    """Hỏi trên terminal xem gợi ý nào thêm vào từ điển. Không có terminal tương tác thì bỏ qua."""
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        out(f"(Có {len(cands)} gợi ý từ điển nhưng không có terminal tương tác; bỏ qua. Dùng --dict-add để thêm tay.)")
        return {}
    out("\nGợi ý thêm vào từ điển GIỮ NGUYÊN tiếng Nhật (danh từ riêng chưa có trong từ điển):")
    for i, c in enumerate(cands, 1):
        out(f"  {i:>3}. {c.term}   [{c.category}] ×{c.count}   «{c.example}»")
    while True:
        ans = ask("Nhập số cần thêm (vd 1,3-5), a = tất cả, Enter = bỏ qua lần này: ")
        try:
            chosen = parse_selection(ans, len(cands))
            break
        except ValueError:
            out("Không hiểu, hãy nhập lại.")
    decision = {cands[i - 1].term: "add" for i in chosen}
    rest = [c for i, c in enumerate(cands, 1) if i not in chosen]
    if rest and ask(f"Không hỏi lại {len(rest)} từ còn lại? [y/N]: ").strip().lower() in ("y", "yes"):
        decision.update({c.term: "ignore" for c in rest})
    return decision


def build_parser():
    ap = argparse.ArgumentParser(
        prog="app.py",
        description="Dịch Excel JP→EN bằng Ollama (sửa XML trực tiếp). "
        "Đầu vào là một file .xlsx/.xlsm hoặc cả một folder.",
    )
    ap.add_argument("input", nargs="?", help="file .xlsx/.xlsm hoặc folder (bỏ trống để mở giao diện)")
    ap.add_argument("-c", "--config", help="đường dẫn file cấu hình .toml (mặc định: config.toml cạnh app.py)")
    ap.add_argument(
        "-o", "--output",
        help="file kết quả (đầu vào là file; mặc định <tên><suffix>.xlsx) "
        "hoặc folder kết quả (đầu vào là folder; mặc định <folder><suffix>)",
    )
    ap.add_argument(
        "--md-out",
        help="file Markdown (đầu vào là file) hoặc folder Markdown (đầu vào là folder; mặc định <folder><suffix><markdown_suffix>)",
    )
    ap.add_argument("-m", "--model", help="ghi đè ollama.model")
    ap.add_argument("--backend", choices=list(BACKENDS), help="ghi đè backend.type (ollama | llama_cpp)")
    ap.add_argument("--model-path", help="file model .gguf (tự chuyển sang backend llama_cpp)")
    ap.add_argument("--host", help="ghi đè ollama.host")
    ap.add_argument("--mode", choices=["replace", "bilingual"], help="ghi đè translate.mode")
    ap.add_argument("--dict", action="append", metavar="FILE", help="thêm file từ điển giữ nguyên tiếng Nhật (dùng được nhiều lần)")
    ap.add_argument("--no-dict", action="store_true", help="không dùng từ điển")
    ap.add_argument(
        "--dict-add", nargs=2, metavar=("NHÓM", "TỪ"),
        help="thêm TỪ vào nhóm NHÓM (vd. screen, item, person, message) trong file từ điển đầu tiên rồi thoát",
    )
    ap.add_argument("--no-suggest", action="store_true", help="không hỏi gợi ý thêm danh từ riêng vào từ điển")
    ap.add_argument("--dict-list", action="store_true", help="in nội dung từ điển rồi thoát")
    ap.add_argument("--no-md", action="store_true", help="không xuất Markdown")
    ap.add_argument("--no-recursive", action="store_true", help="đầu vào là folder: chỉ xử lý file ở cấp trên cùng")
    ap.add_argument("--dry-run", action="store_true", help="chỉ in file nào sẽ được tạo ở đâu, không dịch/ghi gì")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)

    try:
        cfg = load_config(a.config)
    except (OSError, ValueError) as e:
        sys.exit(f"Lỗi cấu hình: {e}")
    if a.model:
        cfg.ollama_model = a.model
    if a.backend:
        cfg.backend = a.backend
    if a.model_path:
        cfg.model_path = Path(a.model_path).expanduser()
        cfg.backend = a.backend or "llama_cpp"
    cfg.refresh()
    if a.host:
        cfg.host = a.host.rstrip("/")
    if a.mode:
        cfg.mode = a.mode
    if a.no_md:
        cfg.md = False
    if a.no_recursive:
        cfg.recursive = False
    if a.dict:
        cfg.dict_files = [Path(f).expanduser() for f in a.dict] + list(cfg.dict_files)
    if a.no_dict:
        cfg.dict_enabled = False
    if a.no_suggest:
        cfg.suggest = False
    if a.dict_add or a.dict_list or a.dict or a.no_dict:
        cfg.reload_dictionary()

    if a.dict_add:
        target = cfg.dict_files[0]
        try:
            added = dictionary.add_term(target, *a.dict_add)
        except (OSError, ValueError) as e:
            sys.exit(f"Lỗi: {e}")
        print(f"{'Đã thêm' if added else 'Đã có sẵn'} «{a.dict_add[1]}» ({a.dict_add[0]}) — {target}")
        return 0
    if a.dict_list:
        d = cfg.dictionary
        if not d:
            print("Từ điển trống.")
        for cat, terms in d.entries.items():
            print(f"[{cat}]")
            for t in terms:
                print(f"  {t}")
        return 0

    if not a.input:
        gui.run_gui(cfg)
        return 0

    path = Path(a.input).expanduser()
    try:
        if path.is_dir():
            res = batch.process_folder(path, cfg, out_dir=a.output, md_dir=a.md_out, dry_run=a.dry_run, review=cli_review)
            return 1 if res.failed else 0
        out = a.output or pipeline.default_out(path, cfg)
        if a.dry_run:
            md = (a.md_out or str(Path(out).with_suffix(".md"))) if cfg.md else None
            print(f"{path} -> {out}" + (f"  (+ {md})" if md else ""))
            return 0
        pipeline.process_xlsx(path, out, cfg, md_path=a.md_out, review=cli_review)
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        sys.exit(f"Lỗi: {e}")
