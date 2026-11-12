"""Từ điển "giữ nguyên tiếng Nhật": tên màn hình, tên item, tên người, message... không bị dịch.

File từ điển là văn bản thuần, mỗi dòng một từ, chia nhóm bằng [tên nhóm]; dòng bắt đầu bằng # là ghi chú:

    [screen]
    ログイン画面
    [person]
    山田太郎

Cách áp dụng khi dịch:
  * Đoạn chữ mà sau khi bỏ các từ trong từ điển không còn tiếng Nhật nào (ví dụ chỉ gồm tên màn hình) -> giữ nguyên, không gọi model.
  * Từ nằm trong câu dài hơn -> thay bằng ký hiệu giữ chỗ [[1]], [[2]]... trước khi gửi cho model, dịch xong
    khôi phục lại đúng chữ gốc. Nếu model làm mất ký hiệu thì thử lại; vẫn mất thì đoạn đó giữ nguyên bản gốc.
Từ dài được ưu tiên khớp trước (「ログイン画面」 trước 「ログイン」). Phân biệt hoa thường.
"""
import hashlib
import re
from pathlib import Path

DEFAULT_CATEGORY = "other"
PLACEHOLDER_NOTE = (
    "Some terms in the text are protected and replaced by placeholders like [[1]], [[2]]. "
    "Copy every placeholder into the translation exactly as written, once for each time it appears. "
    "Do not translate, remove, reorder or change the brackets or numbers of a placeholder."
)
_PH = re.compile(r"\[\[\s*(\d+)\s*\]\]")
_SECTION = re.compile(r"^\[([^\[\]]+)\]$")


class Dictionary:
    _PH_RE = _PH

    def __init__(self, entries=None, files=()):
        self.entries = {}  # {nhóm: [từ, ...]} theo thứ tự trong file
        self.files = [str(f) for f in files]
        self._rx = None
        for cat, term in entries or []:
            self.add_entry(cat, term)

    # ---- nạp / ghi
    @classmethod
    def parse(cls, text):
        d = cls()
        cat = DEFAULT_CATEGORY
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = _SECTION.match(line)
            if m:
                cat = m.group(1).strip() or DEFAULT_CATEGORY
            else:
                d.add_entry(cat, line)
        return d

    @classmethod
    def load(cls, paths, missing=None):
        """Nạp nhiều file. `missing`: list nhận đường dẫn không đọc được (để báo cảnh báo)."""
        d = cls(files=paths)
        for p in paths:
            try:
                text = Path(p).read_text(encoding="utf-8-sig")
            except OSError:
                if missing is not None:
                    missing.append(str(p))
                continue
            for cat, terms in cls.parse(text).entries.items():
                for t in terms:
                    d.add_entry(cat, t)
        return d

    def add_entry(self, category, term):
        term = term.strip()
        if not term:
            return False
        bucket = self.entries.setdefault(category or DEFAULT_CATEGORY, [])
        if term in bucket:
            return False
        bucket.append(term)
        self._rx = None
        return True

    # ---- truy vấn
    def __len__(self):
        return len(self.terms())

    def __bool__(self):
        return bool(self.entries) and len(self) > 0

    def terms(self):
        """Toàn bộ từ (không trùng), dài trước."""
        seen = dict.fromkeys(t for ts in self.entries.values() for t in ts)
        return sorted(seen, key=lambda t: (-len(t), t))

    def category_of(self, term):
        for cat, ts in self.entries.items():
            if term in ts:
                return cat
        return None

    def signature(self):
        """Đổi từ điển thì cache bản dịch cũ không dùng lại được."""
        blob = "\n".join(self.terms())
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def _regex(self):
        if self._rx is None:
            ts = self.terms()
            self._rx = re.compile("|".join(re.escape(t) for t in ts)) if ts else None
        return self._rx

    # ---- bảo vệ / khôi phục
    def protect(self, text):
        """(chữ đã thay từ bằng [[n]], {n: từ gốc}). Không có từ nào khớp -> (text, {})."""
        rx = self._regex()
        if rx is None:
            return text, {}
        ids, mapping = {}, {}

        def repl(m):
            term = m.group(0)
            if term not in ids:
                ids[term] = len(ids) + 1
                mapping[ids[term]] = term
            return f"[[{ids[term]}]]"

        return rx.sub(repl, text), mapping

    def needs_translation(self, text, src_re):
        """False nếu ngoài các từ trong từ điển, đoạn chữ không còn ký tự nguồn (tiếng Nhật) nào."""
        masked, _ = self.protect(text)
        return bool(src_re.search(_PH.sub("", masked)))

    @staticmethod
    def restore(translated, mapping):
        """(chữ đã khôi phục, True) nếu mọi ký hiệu còn nguyên; ngược lại (translated, False)."""
        found = {int(n) for n in _PH.findall(translated)}
        if found != set(mapping):
            return translated, False
        return _PH.sub(lambda m: mapping[int(m.group(1))], translated), True


def add_term(path, category, term):
    """Thêm một từ vào file từ điển (tạo file/nhóm nếu chưa có). Trả về False nếu từ đã có trong nhóm đó."""
    path = Path(path)
    category = (category or DEFAULT_CATEGORY).strip()
    term = term.strip()
    if not term or "\n" in term:
        raise ValueError("Từ cần thêm không được rỗng hoặc nhiều dòng.")
    if _SECTION.match(term):
        raise ValueError("Từ không được có dạng [tên nhóm].")
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    if term in Dictionary.parse("\n".join(lines)).entries.get(category, []):
        return False
    start = None
    for i, raw in enumerate(lines):
        m = _SECTION.match(raw.strip())
        if m and m.group(1).strip() == category:
            start = i
            break
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{category}]", term]
    else:
        end = start + 1
        while end < len(lines) and not _SECTION.match(lines[end].strip()):
            end += 1
        insert_at = end
        while insert_at > start + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        lines.insert(insert_at, term)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True
