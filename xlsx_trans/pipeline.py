"""Dịch MỘT file xlsx/xlsm: gom đoạn cần dịch -> dịch (có cache) -> ghi file mới (+ Markdown)."""
import zipfile
from pathlib import Path

from . import markdown as md_export
from . import ollama as llm
from .cache import TranslationCache
from .xlsx_xml import collect_parts, dedupe_table_names, write_package


def default_out(in_path, cfg):
    """<tên><output.suffix><đuôi>, cạnh file gốc."""
    p = Path(in_path)
    return str(p.with_name(f"{p.stem}{cfg.suffix}{p.suffix}"))


def process_xlsx(
    in_path,
    out_path,
    cfg,
    log=print,
    progress=lambda done, total: None,
    should_stop=lambda: False,
    md_path=None,
    cache=None,
    log_header=True,
):
    """Dịch một file. Trả về (số đoạn đã dịch, số lỗi).

    md_path  nơi ghi Markdown (mặc định: <out_path>.md); chỉ dùng khi cfg.md
    cache    TranslationCache dùng chung (mặc định: cache riêng <out_path>.cache.json)
    log_header  in cảnh báo cấu hình + tóm tắt cấu hình ở đầu (batch tắt đi và in một lần)
    """
    in_path, out_path = Path(in_path), Path(out_path)
    if in_path.resolve() == out_path.resolve():
        raise ValueError("File output phải khác file input (kiểm tra output.suffix trong config).")
    if in_path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError("Chỉ hỗ trợ .xlsx / .xlsm (file .xls cũ hãy Save As .xlsx trước).")

    if log_header:
        for w in cfg.warnings:
            log(f"Cảnh báo: {w}")
        log(
            f"Cấu hình: {', '.join(cfg.source_files) or 'mặc định'} · model {cfg.model} · "
            f"chế độ {cfg.mode}"
        )

    with zipfile.ZipFile(in_path) as zin:
        infos = zin.infolist()
        units, parsed, tables = collect_parts(zin, infos, cfg)
        unique = list(dict.fromkeys(u.text for u in units))
        log(f"Tìm thấy {len(units)} đoạn chữ cần dịch ({len(unique)} chuỗi khác nhau).")

        if cache is None:
            cache = TranslationCache(
                Path(str(out_path) + ".cache.json"), cfg.signature(), cfg.cache, cfg.model
            )
        todo = [t for t in unique if t not in cache]
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
                cache[text] = llm.translate_text(text, cfg)
            except Exception as e:  # noqa: BLE001
                errors += 1
                log(f"Lỗi với đoạn «{text[:30]}…»: {e}")
            progress(i, total)
            if i % 10 == 0:
                log(f"  {i}/{total}")
                cache.save()
        cache.save()

        # Áp bản dịch vào XML
        applied = 0
        for u in units:
            en = cache.get(u.text)
            if not en:
                continue
            u.apply(en if cfg.mode == "replace" else f"{u.text}{u.sep}{en}")
            applied += 1
        dedupe_table_names(tables)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        write_package(zin, infos, out_path, parsed)

    log(f"Xong: đã dịch {applied}/{len(units)} đoạn, {errors} lỗi. Đã lưu: {out_path}")

    if cfg.md:
        target = Path(md_path) if md_path else out_path.with_suffix(".md")

        def gloss(name):  # bản dịch tên sheet, chỉ để tham khảo trong .md (Excel giữ tên gốc)
            if not cfg.src_re.search(name):
                return None
            if name not in cache:
                try:
                    cache[name] = llm.translate_text(name, cfg)
                except Exception:
                    return None
            return cache.get(name)

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            done = md_export.export_markdown(
                out_path, target, gloss, log, max_rows=cfg.md_max_rows, max_cols=cfg.md_max_cols
            )
            if done:
                cache.save()
                log(f"Đã xuất Markdown: {done}")
        except Exception as e:  # noqa: BLE001
            log(f"Không xuất được Markdown: {e}")
    return applied, errors
