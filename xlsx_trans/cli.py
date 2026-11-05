"""Dòng lệnh. Bỏ trống đầu vào để mở giao diện."""
import argparse
import sys
import zipfile
from pathlib import Path

from . import batch, gui, pipeline
from .config import BACKENDS, load_config


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

    if not a.input:
        gui.run_gui(cfg)
        return 0

    path = Path(a.input).expanduser()
    try:
        if path.is_dir():
            res = batch.process_folder(path, cfg, out_dir=a.output, md_dir=a.md_out, dry_run=a.dry_run)
            return 1 if res.failed else 0
        out = a.output or pipeline.default_out(path, cfg)
        if a.dry_run:
            md = (a.md_out or str(Path(out).with_suffix(".md"))) if cfg.md else None
            print(f"{path} -> {out}" + (f"  (+ {md})" if md else ""))
            return 0
        pipeline.process_xlsx(path, out, cfg, md_path=a.md_out)
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        sys.exit(f"Lỗi: {e}")
