"""Dịch CẢ FOLDER, giữ nguyên cấu trúc thư mục con.

Chọn folder `data` thì tạo (cạnh nó):
  data_en/      các file xlsx đã dịch, cùng cấu trúc thư mục con và cùng tên file
  data_en_md/   các file Markdown tương ứng (`a/b.xlsx` -> `a/b.md`)
  data_en.cache.json   cache bản dịch dùng chung cho cả folder (chuỗi lặp giữa các file chỉ dịch 1 lần)

Hậu tố lấy từ config: output.suffix ("_en") và output.markdown_suffix ("_md").
Chỉ xử lý .xlsx/.xlsm; file khác không bị đụng tới (không copy sang folder output).
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import pipeline
from .cache import TranslationCache

SUPPORTED_EXT = (".xlsx", ".xlsm")
UNSUPPORTED_EXT = (".xls", ".xlsb")  # chỉ để báo "bỏ qua", không dịch


@dataclass
class Job:
    src: Path
    rel: Path  # đường dẫn tương đối so với folder đầu vào
    out: Path
    md: Path = None  # None khi tắt markdown


@dataclass
class Plan:
    in_dir: Path
    out_dir: Path
    md_dir: Path  # None khi tắt markdown
    jobs: list
    unsupported: list  # đường dẫn tương đối của file .xls/.xlsb bị bỏ qua


@dataclass
class BatchResult:
    plan: Plan
    ok: list = field(default_factory=list)  # rel các file đã xử lý xong
    failed: list = field(default_factory=list)  # (rel, thông báo lỗi)
    interrupted: list = field(default_factory=list)  # rel file đang dịch dở khi bấm Dừng
    stopped: bool = False
    applied: int = 0
    errors: int = 0


def _is_inside(child, parent):
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def derive_dirs(in_dir, cfg):
    """(folder xlsx output, folder markdown hoặc None) cho một folder đầu vào đã resolve()."""
    in_dir = Path(in_dir)
    if not in_dir.name:
        raise ValueError("Không tạo được tên folder output từ thư mục gốc; hãy chọn một thư mục con.")
    out_dir = in_dir.with_name(in_dir.name + cfg.suffix)
    md_dir = in_dir.with_name(in_dir.name + cfg.suffix + cfg.md_suffix) if cfg.md else None
    return out_dir, md_dir


def _sort_key(rel):
    return [p.casefold() for p in rel.parts]


def plan_folder(in_dir, cfg, out_dir=None, md_dir=None):
    """Quét folder và lập kế hoạch: mỗi file nguồn -> file output (+ markdown). Không ghi gì ra đĩa."""
    in_dir = Path(in_dir).expanduser().resolve()
    if not in_dir.is_dir():
        raise ValueError(f"Không phải thư mục: {in_dir}")

    out_dir = Path(out_dir).expanduser().resolve() if out_dir else None
    md_dir = Path(md_dir).expanduser().resolve() if md_dir else None
    if out_dir is None or (cfg.md and md_dir is None):
        d_out, d_md = derive_dirs(in_dir, cfg)
        out_dir = out_dir or d_out
        md_dir = md_dir or d_md
    if not cfg.md:
        md_dir = None

    for name, d in (("output", out_dir), ("markdown", md_dir)):
        if d is not None and _is_inside(d, in_dir):
            raise ValueError(f"Folder {name} ({d}) không được nằm trong folder đầu vào ({in_dir}).")
    if md_dir is not None and md_dir == out_dir:
        raise ValueError("Folder markdown phải khác folder output.")

    jobs, unsupported = [], []
    for root, dirnames, filenames in os.walk(in_dir):
        dirnames[:] = (
            sorted(d for d in dirnames if not d.startswith(".")) if cfg.recursive else []
        )
        for fn in sorted(filenames):
            if fn.startswith(".") or fn.startswith("~$"):  # file ẩn, file khóa tạm của Excel
                continue
            ext = Path(fn).suffix.lower()
            src = Path(root) / fn
            rel = src.relative_to(in_dir)
            if ext in SUPPORTED_EXT:
                jobs.append(Job(src, rel, out_dir / rel))
            elif ext in UNSUPPORTED_EXT:
                unsupported.append(rel)
    jobs.sort(key=lambda j: _sort_key(j.rel))
    unsupported.sort(key=_sort_key)

    if md_dir is not None:
        groups = {}
        for j in jobs:
            groups.setdefault(j.rel.with_suffix(".md"), []).append(j)
        for md_rel, group in groups.items():
            for j in group:
                # a.xlsx và a.xlsm cùng thư mục: giữ cả đuôi gốc để không ghi đè nhau (a.xlsx.md, a.xlsm.md)
                j.md = md_dir / (md_rel if len(group) == 1 else j.rel.with_name(j.rel.name + ".md"))
    return Plan(in_dir, out_dir, md_dir, jobs, unsupported)


def process_folder(
    in_dir,
    cfg,
    log=print,
    progress=lambda done, total: None,
    file_progress=lambda done, total, rel: None,
    should_stop=lambda: False,
    out_dir=None,
    md_dir=None,
    dry_run=False,
):
    """Dịch mọi .xlsx/.xlsm trong folder (đệ quy nếu cfg.recursive).

    progress       tiến độ trong file đang dịch: (đã dịch, tổng số chuỗi)
    file_progress  tiến độ cả folder: (số file xong, tổng số file, file hiện tại)
    dry_run        chỉ in kế hoạch, không ghi gì
    Một file lỗi (hỏng, bị khóa…) được ghi nhận rồi dịch tiếp file khác nếu cfg.continue_on_error.
    """
    plan = plan_folder(in_dir, cfg, out_dir, md_dir)
    result = BatchResult(plan)
    total = len(plan.jobs)

    for w in cfg.warnings:
        log(f"Cảnh báo: {w}")
    log(f"Cấu hình: {', '.join(cfg.source_files) or 'mặc định'} · model {cfg.model} · chế độ {cfg.mode}")
    log(f"Folder đầu vào : {plan.in_dir}")
    log(f"Folder output  : {plan.out_dir}")
    if plan.md_dir is not None:
        log(f"Folder markdown: {plan.md_dir}")
    log(f"Tìm thấy {total} file Excel" + (f", bỏ qua {len(plan.unsupported)} file .xls/.xlsb" if plan.unsupported else "") + ".")
    for rel in plan.unsupported:
        log(f"  bỏ qua (định dạng cũ, hãy Save As .xlsx): {rel}")

    if dry_run:
        for j in plan.jobs:
            log(f"  {j.rel} -> {j.out}" + (f"  (+ {j.md})" if j.md else ""))
        return result
    if not total:
        log("Không có file nào để dịch.")
        return result

    cache = TranslationCache(str(plan.out_dir) + ".cache.json", cfg.signature(), cfg.cache, cfg.model)
    indent = lambda m: log("    " + m)  # noqa: E731

    for i, job in enumerate(plan.jobs, 1):
        if should_stop():
            result.stopped = True
            log("Đã dừng theo yêu cầu.")
            break
        file_progress(i - 1, total, job.rel)
        log(f"[{i}/{total}] {job.rel}")
        try:
            applied, errors = pipeline.process_xlsx(
                job.src, job.out, cfg, log=indent, progress=progress, should_stop=should_stop,
                md_path=job.md, cache=cache, log_header=False,
            )
        except Exception as e:  # noqa: BLE001
            result.failed.append((job.rel, str(e)))
            log(f"    LỖI: {e}")
            if not cfg.continue_on_error:
                log("Dừng vì có file lỗi (batch.continue_on_error = false).")
                break
            continue
        result.applied += applied
        result.errors += errors
        if should_stop():  # bấm Dừng khi file này đang dịch: file output có thể mới dịch một phần
            result.interrupted.append(job.rel)
            result.stopped = True
            log("Đã dừng theo yêu cầu (file này có thể chưa dịch xong; chạy lại sẽ dùng cache để tiếp tục).")
            break
        result.ok.append(job.rel)
        file_progress(i, total, job.rel)

    log(
        f"Hoàn tất: {len(result.ok)}/{total} file, {len(result.failed)} file lỗi, "
        f"{result.errors} đoạn lỗi dịch. Kết quả: {plan.out_dir}"
    )
    for rel, err in result.failed:
        log(f"  lỗi: {rel}: {err}")
    return result
