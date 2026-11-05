"""Xuất workbook (đã dịch) ra một file Markdown, mỗi sheet một mục.

Giữ NGUYÊN tên sheet gốc, số dòng và chữ cột của Excel để đối chiếu. Cần openpyxl để đọc dữ liệu.
"""
import datetime
import posixpath
import warnings
import zipfile
from pathlib import Path

from .xlsx_xml import A, NS_A, NS_MC, NS_R, NS_XDR, NSMAP, etree, parse


def md_fmt(v):
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


def md_cell(v):
    s = md_fmt(v).strip().replace("|", "\\|")
    return s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def resolve_path(base_dir, target):
    if target.startswith("/"):
        return target[1:]
    return posixpath.normpath(posixpath.join(base_dir, target))


def sheet_textboxes(zf):
    """{tên sheet: [(vị trí gần ô, text), ...]} lấy từ drawings của từng sheet."""
    from openpyxl.utils import get_column_letter

    out = {}
    try:
        wb = parse(zf.read("xl/workbook.xml"))
        rels = parse(zf.read("xl/_rels/workbook.xml.rels"))
        rid2t = {r.get("Id"): r.get("Target") for r in rels}
        names = set(zf.namelist())
        for sh in wb.xpath("//m:sheets/m:sheet", namespaces=NSMAP):
            name = sh.get("name")
            tgt = rid2t.get(sh.get("{%s}id" % NS_R))
            if not tgt:
                continue
            spath = resolve_path("xl", tgt)
            relp = posixpath.join(posixpath.dirname(spath), "_rels", posixpath.basename(spath) + ".rels")
            if relp not in names:
                continue
            for rel in parse(zf.read(relp)):
                if not rel.get("Type", "").endswith("/drawing"):
                    continue
                dpath = resolve_path(posixpath.dirname(spath), rel.get("Target"))
                if dpath not in names:
                    continue
                droot = parse(zf.read(dpath))
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
    """Xuất toàn bộ workbook ra 1 file Markdown. gloss(tên sheet) -> bản dịch tên sheet hoặc None."""
    try:
        import openpyxl
        from openpyxl.utils import get_column_letter
    except ImportError:
        log("Bỏ qua xuất Markdown: thiếu openpyxl (pip install openpyxl).")
        return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # openpyxl cảnh báo shape khi đọc; file gốc không bị ảnh hưởng
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    with zipfile.ZipFile(xlsx_path) as zf:
        boxes = sheet_textboxes(zf)

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
            last = max((i + 1 for i, v in enumerate(vals) if md_fmt(v).strip() != ""), default=0)
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
                cells = [md_cell(v) for v in vals[:max_col]] + [""] * (max_col - len(vals[:max_col]))
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
