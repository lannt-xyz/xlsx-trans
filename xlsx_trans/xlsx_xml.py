"""Đọc/ghi XML bên trong file .xlsx: gom các đoạn cần dịch và ghi lại package.

Không mở workbook bằng thư viện bảng tính nên shape, hình, biểu đồ, định dạng, công thức, macro
được giữ nguyên; chỉ các part có đoạn cần dịch mới bị ghi lại.
"""
import re
import sys
import zipfile
from typing import Callable, NamedTuple

try:
    from lxml import etree
except ImportError:  # pragma: no cover
    sys.exit("Thiếu thư viện lxml. Cài bằng:  pip install lxml")

NS_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
M = "{%s}" % NS_M
A = "{%s}" % NS_A
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
NSMAP = {"m": NS_M, "a": NS_A}

RE_SHARED = re.compile(r"^xl/sharedStrings\.xml$")
RE_SHEET = re.compile(r"^xl/worksheets/[^/]+\.xml$")
RE_COMMENTS = re.compile(r"^xl/comments(/[^/]*|[^/]*)\.xml$")
RE_DRAWML = re.compile(r"^xl/(drawings/drawing|charts/chart|diagrams/data)[^/]*\.xml$")
RE_TABLE = re.compile(r"^xl/tables/table[^/]*\.xml$")


class Unit(NamedTuple):
    """Một đoạn chữ cần dịch: nội dung gốc, ký tự nối khi song ngữ, hàm ghi bản dịch vào XML."""

    text: str
    sep: str
    apply: Callable[[str], None]


def parse(data):
    parser = etree.XMLParser(huge_tree=True, resolve_entities=False)
    return etree.fromstring(data, parser)


XML_DECL = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'


def serialize(root):
    """XML kèm khai báo kiểu Excel (nháy kép, standalone="yes")."""
    return XML_DECL + etree.tostring(root, encoding="UTF-8")


def set_runs(ts, new, preserve=True):
    """Đặt toàn bộ bản dịch vào run đầu tiên, làm rỗng các run còn lại.

    preserve: thêm xml:space="preserve" (chỉ đúng với <t> của SpreadsheetML; <a:t> của DrawingML không có thuộc tính này).
    """
    ts[0].text = new
    if preserve:
        ts[0].set(XML_SPACE, "preserve")
    for t in ts[1:]:
        t.text = ""


def collect_sml(conts, units, rx, sep):
    """conts: các phần tử <si>, <is>, <text> của SpreadsheetML (có thể có rich runs)."""
    for cont in conts:
        ts = cont.xpath(".//m:t[not(ancestor::m:rPh)]", namespaces=NSMAP)
        if not ts:
            continue
        text = "".join(t.text or "" for t in ts)
        if not rx.search(text):
            continue

        def apply(new, cont=cont, ts=ts):
            set_runs(ts, new)
            # furigana cũ không còn đúng nữa
            for e in cont.xpath("./m:rPh|./m:phoneticPr", namespaces=NSMAP):
                cont.remove(e)

        units.append(Unit(text, sep, apply))


def collect_drawingml(root, units, rx, sep):
    """Mỗi đoạn <a:p> là một đơn vị dịch (text box, shape, tiêu đề chart...)."""
    for p in root.iter(A + "p"):
        ts = [r.find(A + "t") for r in p.findall(A + "r")]
        ts = [t for t in ts if t is not None]
        if not ts:
            continue
        text = "".join(t.text or "" for t in ts)
        if not rx.search(text):
            continue

        def apply(new, ts=ts):
            set_runs(ts, new, preserve=False)

        units.append(Unit(text, sep, apply))


class TableRef:
    """Một Table: part chứa nó, các phần tử tableColumn, tên cột gốc, chỉ số cột bị đổi tên do trùng."""

    def __init__(self, part, root, cols):
        self.part, self.root, self.cols = part, root, cols
        self.orig = [c.get("name", "") for c in cols]
        self.deduped = []


def collect_table(root, tables, units, rx, sep, part=""):
    cols = root.xpath("//m:tableColumn", namespaces=NSMAP)
    if not cols:
        return
    for c in cols:
        raw = c.get("name", "")
        text = raw.replace("_x000a_", "\n")
        if not rx.search(text):
            continue

        def apply(new, c=c):
            c.set("name", new.replace("\n", "_x000a_"))

        units.append(Unit(text, sep, apply))
    tables.append(TableRef(part, root, cols))


def dedupe_table_names(tables):
    """Tên cột Table phải duy nhất (không phân biệt hoa thường); bản dịch trùng thì thêm số 2, 3…"""
    for t in tables:
        seen = set()
        for i, c in enumerate(t.cols):
            n = base = c.get("name", "")
            k = 2
            while n.lower() in seen:
                n = f"{base}{k}"
                k += 1
            if n != base:
                c.set("name", n)
                t.deduped.append(i)
            seen.add(n.lower())


def collect_parts(zin, infos, cfg):
    """Quét các part của package theo cfg.targets.

    Trả về (units, parsed, tables):
      units   danh sách Unit cần dịch
      parsed  {tên part: root XML} chỉ gồm các part có đoạn cần dịch (những part khác giữ nguyên byte)
      tables  các nhóm tableColumn để khử trùng tên sau khi dịch
    """
    tg = cfg.targets
    rx = cfg.src_re
    units, parsed, tables = [], {}, []
    for info in infos:
        n = info.filename
        root = None
        before = len(units)
        if RE_SHARED.match(n):
            if not tg["cells"]:
                continue
            root = parse(zin.read(n))
            collect_sml(root.xpath("//m:si", namespaces=NSMAP), units, rx, cfg.cell_sep)
        elif RE_COMMENTS.match(n):
            if not tg["comments"]:
                continue
            root = parse(zin.read(n))
            collect_sml(root.xpath("//m:comment/m:text", namespaces=NSMAP), units, rx, cfg.cell_sep)
        elif RE_SHEET.match(n):
            if not tg["cells"]:
                continue
            data = zin.read(n)
            if b"inlineStr" not in data:
                continue
            root = parse(data)
            collect_sml(
                root.xpath("//m:c[@t='inlineStr']/m:is", namespaces=NSMAP), units, rx, cfg.cell_sep
            )
        elif RE_DRAWML.match(n):
            kind = (
                "shapes" if n.startswith("xl/drawings/")
                else "charts" if n.startswith("xl/charts/")
                else "diagrams"
            )
            if not tg[kind]:
                continue
            root = parse(zin.read(n))
            collect_drawingml(root, units, rx, cfg.shape_sep)
        elif RE_TABLE.match(n):
            if not tg["cells"]:  # tên cột Table phải trùng chữ ở ô tiêu đề, nên đi cùng với `cells`
                continue
            root = parse(zin.read(n))
            collect_table(root, tables, units, rx, cfg.cell_sep, n)
        if root is not None and len(units) > before:
            parsed[n] = root  # chỉ ghi lại part có đoạn cần dịch
    return units, parsed, tables


def write_package(zin, infos, out_path, parsed):
    """Ghi file mới: copy nguyên mọi part (giữ thứ tự, kiểu nén), chỉ thay các part trong parsed."""
    with zipfile.ZipFile(out_path, "w") as zout:
        for info in infos:
            data = serialize(parsed[info.filename]) if info.filename in parsed else zin.read(info.filename)
            # ZipInfo mới: không mang theo extra field / cờ / offset cũ của file gốc
            zi = zipfile.ZipInfo(info.filename, info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zi.create_system = info.create_system
            zout.writestr(zi, data)
