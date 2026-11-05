"""Dữ liệu và tiện ích dùng chung cho các test.

File xlsx mẫu được dựng thủ công bằng zipfile (không phụ thuộc openpyxl) để kiểm soát chính xác
XML: shared strings có rich text + furigana (rPh), inline string, công thức, comment, table,
shape trong mc:AlternateContent (Choice + Fallback), biểu đồ và SmartArt.
"""
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xlsx_trans import config, ollama, pipeline  # noqa: E402
from xlsx_trans.xlsx_xml import A, NSMAP, parse  # noqa: E402

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
DML = "http://schemas.openxmlformats.org/drawingml/2006/main"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
CT = "application/vnd.openxmlformats-officedocument"
DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

# Số đoạn chữ tiếng Nhật trong file mẫu và số chuỗi khác nhau (tên cột Table trùng header cell).
UNIT_COUNT = 17
UNIQUE_COUNT = 13

# Các part có chữ tiếng Nhật => bị ghi lại khi dịch. Mọi part khác phải giữ nguyên từng byte.
P_SHARED = "xl/sharedStrings.xml"
P_SHEET1 = "xl/worksheets/sheet1.xml"
P_COMMENTS = "xl/comments1.xml"
P_DRAWING = "xl/drawings/drawing1.xml"
P_CHART = "xl/charts/chart1.xml"
P_DIAGRAM = "xl/diagrams/data1.xml"
P_TABLE = "xl/tables/table1.xml"
TRANSLATED_PARTS = {P_SHARED, P_SHEET1, P_COMMENTS, P_DRAWING, P_CHART, P_DIAGRAM, P_TABLE}


def _p(body):
    return (DECL + body).encode("utf-8")


def fixture_parts():
    """dict tên part -> bytes (giữ thứ tự: sharedStrings đứng trước các sheet)."""
    parts = {}
    parts["[Content_Types].xml"] = _p(
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{CT}.spreadsheetml.sheet.main+xml"/>'
        f'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="{CT}.spreadsheetml.worksheet+xml"/>'
        f'<Override PartName="/xl/worksheets/sheet2.xml" ContentType="{CT}.spreadsheetml.worksheet+xml"/>'
        f'<Override PartName="/xl/sharedStrings.xml" ContentType="{CT}.spreadsheetml.sharedStrings+xml"/>'
        f'<Override PartName="/xl/tables/table1.xml" ContentType="{CT}.spreadsheetml.table+xml"/>'
        f'<Override PartName="/xl/comments1.xml" ContentType="{CT}.spreadsheetml.comments+xml"/>'
        f'<Override PartName="/xl/drawings/drawing1.xml" ContentType="{CT}.drawing+xml"/>'
        f'<Override PartName="/xl/charts/chart1.xml" ContentType="{CT}.drawingml.chart+xml"/>'
        "</Types>"
    )
    parts["_rels/.rels"] = _p(
        f'<Relationships xmlns="{PKG_REL}">'
        f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    parts["xl/workbook.xml"] = _p(
        f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'
        '<sheet name="売上" sheetId="1" r:id="rId1"/>'
        '<sheet name="Summary" sheetId="2" r:id="rId2"/>'
        "</sheets></workbook>"
    )
    parts["xl/_rels/workbook.xml.rels"] = _p(
        f'<Relationships xmlns="{PKG_REL}">'
        f'<Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{REL}/worksheet" Target="worksheets/sheet2.xml"/>'
        f'<Relationship Id="rId3" Type="{REL}/sharedStrings" Target="sharedStrings.xml"/>'
        "</Relationships>"
    )
    parts[P_SHARED] = _p(
        f'<sst xmlns="{MAIN}" count="9" uniqueCount="9">'
        "<si><t>名前</t></si>"  # 0
        "<si><t>数量</t></si>"  # 1
        "<si><t>備考</t></si>"  # 2
        "<si><t>りんご</t></si>"  # 3
        # 4: rich text + furigana (rPh/phoneticPr)
        "<si><r><t>新鮮</t></r><r><t>です</t></r>"
        '<rPh sb="0" eb="2"><t>シンセン</t></rPh><phoneticPr fontId="0"/></si>'
        "<si><t>ABC-123</t></si>"  # 5: không phải tiếng Nhật
        '<si><t xml:space="preserve">1行目\n2行目</t></si>'  # 6: nhiều dòng
        "<si><t>良い|悪い</t></si>"  # 7: có ký tự |
        "<si><t>合計</t></si>"  # 8
        "</sst>"
    )
    parts[P_SHEET1] = _p(
        f'<worksheet xmlns="{MAIN}" xmlns:r="{REL}"><dimension ref="A1:D5"/><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>3</v></c><c r="B2"><v>3</v></c><c r="C2" t="s"><v>4</v></c></row>'
        '<row r="3"><c r="A3" t="inlineStr"><is><t>みかん</t></is></c><c r="B3"><v>5</v></c>'
        '<c r="C3" t="s"><v>5</v></c><c r="D3" t="str"><f>A2&amp;"x"</f><v>りんごx</v></c></row>'
        '<row r="5"><c r="A5" t="s"><v>6</v></c><c r="B5" t="s"><v>7</v></c></row>'
        '</sheetData><tableParts count="1"><tablePart r:id="rId1"/></tableParts></worksheet>'
    )
    parts["xl/worksheets/sheet2.xml"] = _p(
        f'<worksheet xmlns="{MAIN}"><sheetData>'
        '<row r="3"><c r="B3" t="s"><v>8</v></c><c r="C3"><v>8</v></c></row>'
        "</sheetData></worksheet>"
    )
    parts["xl/worksheets/_rels/sheet1.xml.rels"] = _p(
        f'<Relationships xmlns="{PKG_REL}">'
        f'<Relationship Id="rId1" Type="{REL}/table" Target="../tables/table1.xml"/>'
        f'<Relationship Id="rId2" Type="{REL}/comments" Target="../comments1.xml"/>'
        f'<Relationship Id="rId3" Type="{REL}/drawing" Target="../drawings/drawing1.xml"/>'
        "</Relationships>"
    )
    parts[P_TABLE] = _p(
        f'<table xmlns="{MAIN}" id="1" name="T1" displayName="T1" ref="A1:C3">'
        '<autoFilter ref="A1:C3"/><tableColumns count="3">'
        '<tableColumn id="1" name="名前"/><tableColumn id="2" name="数量"/><tableColumn id="3" name="備考"/>'
        "</tableColumns></table>"
    )
    parts[P_COMMENTS] = _p(
        f'<comments xmlns="{MAIN}"><authors><author>me</author></authors><commentList>'
        '<comment ref="A2" authorId="0"><text><r><t>確認して</t></r><r><t>ください</t></r></text></comment>'
        "</commentList></comments>"
    )
    parts[P_DRAWING] = _p(
        f'<xdr:wsDr xmlns:xdr="{XDR}" xmlns:a="{DML}" xmlns:mc="{MC}"><xdr:twoCellAnchor>'
        "<xdr:from><xdr:col>4</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>5</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
        "<xdr:to><xdr:col>6</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>8</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>"
        "<mc:AlternateContent>"
        '<mc:Choice Requires="a14"><xdr:sp><xdr:txBody><a:bodyPr/>'
        "<a:p><a:r><a:t>注意</a:t></a:r><a:r><a:t>事項です</a:t></a:r></a:p>"
        "<a:p><a:r><a:t>OK 123</a:t></a:r></a:p>"
        "</xdr:txBody></xdr:sp></mc:Choice>"
        "<mc:Fallback><xdr:sp><xdr:txBody><a:bodyPr/>"
        "<a:p><a:r><a:t>注意事項です</a:t></a:r></a:p>"
        "</xdr:txBody></xdr:sp></mc:Fallback>"
        "</mc:AlternateContent><xdr:clientData/></xdr:twoCellAnchor></xdr:wsDr>"
    )
    parts[P_CHART] = _p(
        '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        f'xmlns:a="{DML}"><c:chart><c:title><c:tx><c:rich><a:bodyPr/>'
        "<a:p><a:r><a:t>売上グラフ</a:t></a:r></a:p></c:rich></c:tx></c:title></c:chart></c:chartSpace>"
    )
    parts[P_DIAGRAM] = _p(
        '<dgm:dataModel xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" '
        f'xmlns:a="{DML}"><dgm:ptLst><dgm:pt modelId="1"><dgm:t><a:bodyPr/>'
        "<a:p><a:r><a:t>図表</a:t></a:r></a:p></dgm:t></dgm:pt></dgm:ptLst></dgm:dataModel>"
    )
    return parts


def build_fixture(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in fixture_parts().items():
            z.writestr(name, data)
    return path


def make_tree(root):
    """Tạo cây thư mục mẫu cho test batch dưới `root`.

    File Excel hợp lệ (6): a.xlsx, b.xlsm, sub/c.xlsx, sub/x.xlsx, sub/x.xlsm, sub/deep/er/d.xlsx
    Bị bỏ qua: old.xls (định dạng cũ, báo riêng), ~$lock.xlsx, .hidden/h.xlsx, notes.txt, onlytxt/readme.txt
    """
    root = Path(root)
    for rel in ["a.xlsx", "b.xlsm", "sub/c.xlsx", "sub/x.xlsx", "sub/x.xlsm", "sub/deep/er/d.xlsx"]:
        build_fixture(root / rel)
    for rel in ["old.xls", "~$lock.xlsx", ".hidden/h.xlsx", "notes.txt", "onlytxt/readme.txt"]:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"khong phai excel")
    (root / "empty").mkdir(exist_ok=True)
    return root


VALID_FILES = {"a.xlsx", "b.xlsm", "sub/c.xlsx", "sub/x.xlsx", "sub/x.xlsm", "sub/deep/er/d.xlsx"}


def files_under(root):
    """Tập đường dẫn tương đối (posix) của mọi file dưới root."""
    root = Path(root)
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def read_zip(path):
    with zipfile.ZipFile(path) as z:
        return {i.filename: z.read(i.filename) for i in z.infolist()}


# ---------------------------------------------------------------- cấu hình & mock
def default_cfg(**overrides):
    """Config mặc định trong code, không phụ thuộc config.toml thật. Markdown tắt cho nhanh."""
    with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "APP_DIR", Path(d)):
        cfg = config.load_config()
    cfg.md = False
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


class FakeTranslator:
    """Thay ollama.translate_text: trả "EN[<text>]", ghi lại các lần gọi, có thể giả lập lỗi."""

    def __init__(self, fail_on=()):
        self.calls = []
        self.fail_on = set(fail_on)

    def __call__(self, text, cfg):
        self.calls.append(text)
        if text in self.fail_on:
            raise RuntimeError("giả lập lỗi")
        return f"EN[{text}]"


def patch_translate(fake):
    return mock.patch.object(ollama, "translate_text", fake)


def run_process(src, out, cfg, fake=None, **kw):
    """Chạy pipeline.process_xlsx với translate_text giả. Trả về (kết quả, log, fake)."""
    fake = fake or FakeTranslator()
    logs = []
    with patch_translate(fake):
        res = pipeline.process_xlsx(src, out, cfg, log=logs.append, **kw)
    return res, logs, fake


# ---------------------------------------------------------------- đọc XML
def sst_texts(data):
    root = parse(data)
    return [
        "".join(t.text or "" for t in si.xpath(".//m:t[not(ancestor::m:rPh)]", namespaces=NSMAP))
        for si in root.xpath("//m:si", namespaces=NSMAP)
    ]


def a_texts(data):
    return [t.text or "" for t in parse(data).iter(A + "t")]
