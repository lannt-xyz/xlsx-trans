"""Giữ Excel Table nhất quán sau khi dịch tên cột (nếu không, Excel báo file lỗi và đòi "repair").

Excel yêu cầu:
  1. chữ ở ô tiêu đề của Table == tên cột trong xl/tables/tableN.xml;
  2. tên cột duy nhất (không phân biệt hoa thường);
  3. công thức tham chiếu cột theo tên (Table1[[#This Row],[名前]], [@名前]...) dùng đúng tên mới.
xlsx_xml.dedupe_table_names lo (2); module này lo (1) cho cột bị đổi tên do trùng và (3).
"""
import posixpath
import re

from .xlsx_xml import M, NSMAP, XML_SPACE, parse

REL_TABLE = "/relationships/table"
FORMULA_TAGS = ("f", "formula", "formula1", "formula2", "calculatedColumnFormula", "totalsRowFormula", "definedName")
RE_FORMULA_PART = re.compile(r"^xl/(worksheets/[^/]+|workbook|tables/[^/]+)\.xml$")


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def col_letters(index):
    s, n = "", index + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_ref(ref):
    m = re.fullmatch(r"\$?([A-Za-z]+)\$?(\d+)", ref)
    return col_index(m.group(1)), int(m.group(2))


def table_sheets(zin):
    """{đường dẫn part của table: đường dẫn part của sheet chứa nó}, đọc từ các file .rels của sheet."""
    result = {}
    for name in zin.namelist():
        m = re.fullmatch(r"xl/worksheets/_rels/([^/]+)\.rels", name)
        if not m:
            continue
        rels = parse(zin.read(name))
        for rel in rels:
            if rel.get("Type", "").endswith(REL_TABLE) and rel.get("TargetMode") != "External":
                target = rel.get("Target", "")
                path = target[1:] if target.startswith("/") else posixpath.normpath(posixpath.join("xl/worksheets", target))
                result[path] = "xl/worksheets/" + m.group(1)
    return result


def formula_name(name):
    """Tên cột viết trong công thức: [ ] # ' phải đứng sau dấu '."""
    return re.sub(r"([\[\]#'])", r"'\1", name)


def _cell_text(cell, shared):
    t = cell.get("t")
    if t == "s":
        v = cell.find(M + "v")
        try:
            return shared[int(v.text)]
        except (TypeError, ValueError, IndexError, AttributeError):
            return None
    if t == "inlineStr":
        return "".join(x.text or "" for x in cell.xpath(".//m:is//m:t[not(ancestor::m:rPh)]", namespaces=NSMAP))
    return None


def _set_inline(cell, text):
    for child in list(cell):
        cell.remove(child)
    cell.set("t", "inlineStr")
    is_ = cell.makeelement(M + "is")
    t = is_.makeelement(M + "t")
    t.text = text
    t.set(XML_SPACE, "preserve")
    is_.append(t)
    cell.append(is_)


def _shared_texts(zin, parsed):
    root = parsed.get("xl/sharedStrings.xml")
    if root is None:
        if "xl/sharedStrings.xml" not in zin.namelist():
            return []
        root = parse(zin.read("xl/sharedStrings.xml"))
    return [
        "".join(t.text or "" for t in si.xpath(".//m:t[not(ancestor::m:rPh)]", namespaces=NSMAP))
        for si in root.xpath("//m:si", namespaces=NSMAP)
    ]


def fix_deduped_headers(zin, parsed, tables, log=lambda m: None):
    """Cột bị đổi tên vì trùng (vd. hai tiêu đề cùng dịch ra "Remarks") thì ô tiêu đề cũng phải đổi theo."""
    pending = [t for t in tables if t.deduped]
    if not pending:
        return
    sheets_of = table_sheets(zin)
    shared = None
    for t in pending:
        sheet = sheets_of.get(t.part)
        ref = t.root.get("ref")
        if not sheet or not ref or t.root.get("headerRowCount") == "0":
            log(f"Cảnh báo: không tìm được ô tiêu đề của {t.part}; Excel có thể báo lỗi Table.")
            continue
        root = parsed.get(sheet)
        if root is None:
            root = parse(zin.read(sheet))
        first_col, header_row = split_ref(ref.split(":")[0])
        changed = False
        for i in t.deduped:
            name = t.cols[i].get("name", "").replace("_x000a_", "\n")
            addr = f"{col_letters(first_col + i)}{header_row}"
            cells = root.xpath(f"//m:c[@r='{addr}']", namespaces=NSMAP)
            if not cells:
                continue
            if shared is None:
                shared = _shared_texts(zin, parsed)
            if _cell_text(cells[0], shared) != name:
                _set_inline(cells[0], name)
                changed = True
        if changed:
            parsed[sheet] = root


def rewrite_references(zin, infos, parsed, tables):
    """Đổi `[tên cũ]` / `[@tên cũ]` trong công thức thành tên cột mới ở sheet, workbook (defined name) và table."""
    renames = {}
    for t in tables:
        for c, old in zip(t.cols, t.orig):
            new = c.get("name", "")
            if new != old and "_x000a_" not in old and "_x000a_" not in new:
                renames[old] = new
    if not renames:
        return 0
    pairs = []
    for old, new in renames.items():
        nf = formula_name(new)
        pairs += [(f"[{old}]", f"[{nf}]"), (f"[@{old}]", f"[@{nf}]")]

    def rewrite(text):
        for a, b in pairs:
            text = text.replace(a, b)
        return text

    touched = 0
    for info in infos:
        n = info.filename
        if not RE_FORMULA_PART.match(n):
            continue
        root = parsed.get(n)
        if root is None:
            data = zin.read(n)
            if not any(old.encode("utf-8") in data for old in renames):
                continue
            root = parse(data)
        changed = False
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            local = el.tag.rsplit("}", 1)[-1]
            if local in FORMULA_TAGS and el.text:
                new_text = rewrite(el.text)
                if new_text != el.text:
                    el.text = new_text
                    changed = True
        if changed:
            parsed[n] = root
            touched += 1
    return touched


def sync(zin, infos, parsed, tables, log=lambda m: None):
    """Gọi sau khi đã áp bản dịch và dedupe_table_names; có thể thêm part vào `parsed`."""
    if not tables:
        return
    fix_deduped_headers(zin, parsed, tables, log)
    n = rewrite_references(zin, infos, parsed, tables)
    if n:
        log(f"Đã cập nhật tham chiếu tên cột Table trong {n} part.")
