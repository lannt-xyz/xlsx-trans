"""Dịch THỦ CÔNG qua một chat bên ngoài (vd. công cụ chat nội bộ): app chia nội dung thành các khối vừa cửa sổ
ngữ cảnh, bạn copy từng khối vào chat, dán kết quả lại, app ghi vào cache rồi tự tạo file xlsx / md.

Luồng: ManualSession.scan() -> blocks -> (copy block.prompt vào chat) -> apply_output(block, kết quả) -> finish().
Bản dịch nằm trong cache; finish() chạy pipeline với backend "manual" (không gọi model, chỉ ghép cache vào XML).
"""
import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import batch, pipeline
from .cache import TranslationCache
from .tokens import TokenCounter

BR = "<br>"
RE_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
RE_ITEM = re.compile(r"^\s*\[(\d+)\]\s?(.*)$")


@dataclass
class Item:
    id: int
    text: str  # đoạn gốc (khóa của cache)
    masked: str  # đoạn gửi đi: đã thay từ khóa trong từ điển bằng [[n]]
    mapping: dict = field(default_factory=dict)


@dataclass
class Block:
    index: int
    items: list
    prompt: str
    tokens: int


@dataclass
class ApplyResult:
    saved: list = field(default_factory=list)  # id đã ghi vào cache
    missing: list = field(default_factory=list)  # id không có trong kết quả dán vào
    bad: list = field(default_factory=list)  # [(id, lý do)] có dòng nhưng không dùng được
    suspect: list = field(default_factory=list)  # id đã lưu nhưng vẫn còn tiếng Nhật (có thể chưa dịch)
    extra: int = 0  # số dòng có số không thuộc khối này

    @property
    def retry_ids(self):
        return list(self.missing) + [i for i, _ in self.bad]


def encode_item(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", BR)


def decode_item(text):
    return RE_BR.sub("\n", text)


def parse_output(text):
    """{id: chữ}. Bỏ dòng ```; dòng không bắt đầu bằng [n] được nối vào mục trước (chat tự xuống dòng)."""
    out, cur = {}, None
    for line in text.splitlines():
        if line.strip().startswith("```"):
            continue
        m = RE_ITEM.match(line)
        if m:
            cur = int(m.group(1))
            out[cur] = m.group(2).strip()
        elif cur is not None and line.strip():
            out[cur] = (out[cur] + " " + line.strip()).strip()
    return out


def render_prompt(cfg, items):
    head = (cfg.system_prompt.strip() + "\n\n" + cfg.manual_instruction.strip()).strip()
    body = "\n".join(f"[{it.id}] {encode_item(it.masked)}" for it in items)
    return f"{head}\n\nITEMS:\n{body}\n"


def make_blocks(items, cfg, counter):
    """Chia items (đã đánh số lại từ 1 trong mỗi khối) thành các khối <= cfg.block_tokens token."""
    head_tokens = counter(render_prompt(cfg, []))
    blocks, cur, used = [], [], head_tokens

    def flush():
        nonlocal cur, used
        if cur:
            blocks.append(_build(len(blocks) + 1, cur, cfg, counter))
        cur, used = [], head_tokens

    for it in items:
        cost = counter(f"[{len(cur) + 1}] {encode_item(it.masked)}") + 1
        if cur and (used + cost > cfg.block_tokens or len(cur) >= cfg.block_max_items):
            flush()
            cost = counter(f"[1] {encode_item(it.masked)}") + 1
        cur.append(Item(len(cur) + 1, it.text, it.masked, it.mapping))
        used += cost
    flush()
    return blocks


def _build(index, items, cfg, counter):
    prompt = render_prompt(cfg, items)
    return Block(index, items, prompt, counter(prompt))


class ManualSession:
    def __init__(self, cfg, input_path, out_dir=None, md_dir=None, counter=None):
        self.cfg = copy.copy(cfg)
        self.cfg.backend = "manual"
        self.cfg.cache = True
        self.cfg.refresh()
        self.input = Path(input_path)
        self.out_dir, self.md_dir = out_dir, md_dir
        self.counter = counter or TokenCounter(cfg.manual_tokenizer)
        self.is_folder = self.input.is_dir()
        self.cache = None
        self.total = 0
        self._unique = []
        self.blocks = []

    # ---- nơi lưu cache (giống pipeline / batch để finish() dùng lại đúng file)
    def cache_path(self):
        if self.is_folder:
            plan = batch.plan_folder(self.input, self.cfg, self.out_dir, self.md_dir)
            return Path(str(plan.out_dir) + ".cache.json")
        out = self.out_dir or pipeline.default_out(self.input, self.cfg)
        return Path(str(out) + ".cache.json")

    def _texts(self):
        if self.is_folder:
            plan = batch.plan_folder(self.input, self.cfg, self.out_dir, self.md_dir)
            return [t for job in plan.jobs for t in pipeline.scan_texts(job.src, self.cfg)]
        return pipeline.scan_texts(self.input, self.cfg)

    def scan(self):
        """Quét file/folder, bỏ chuỗi đã có trong cache / không cần dịch, chia khối. Trả về danh sách khối."""
        cfg = self.cfg
        self.cache = TranslationCache(self.cache_path(), cfg.signature(), True, cfg.model)
        unique = list(dict.fromkeys(self._texts()))
        if cfg.dictionary:
            unique = [t for t in unique if cfg.dictionary.needs_translation(t, cfg.src_re)]
        self.total = len(unique)
        self._unique = unique
        items = []
        for t in unique:
            if t in self.cache:
                continue
            masked, mapping = cfg.dictionary.protect(t) if cfg.dictionary else (t, {})
            items.append(Item(0, t, masked, mapping))
        self.blocks = make_blocks(items, cfg, self.counter)
        return self.blocks

    def done_count(self):
        """Số chuỗi (trong tổng cần dịch) đã có bản dịch trong cache."""
        return sum(1 for t in self._unique if t in self.cache) if self.cache is not None else 0

    # ---- nhận kết quả từ chat
    def apply_output(self, block, text):
        from .dictionary import Dictionary

        got = parse_output(text)
        res = ApplyResult(extra=len([i for i in got if i not in {it.id for it in block.items}]))
        for it in block.items:
            raw = got.get(it.id)
            if raw is None or not raw.strip():
                res.missing.append(it.id)
                continue
            tr = decode_item(raw).strip()
            if it.mapping:
                tr, ok = Dictionary.restore(tr, it.mapping)
                if not ok:
                    res.bad.append((it.id, "mất hoặc sai ký hiệu [[n]] của từ điển"))
                    continue
            elif self.cfg.src_re.search(tr):
                res.suspect.append(it.id)
            self.cache[it.text] = tr
            res.saved.append(it.id)
        self.cache.save()
        saved = {it.text for it in block.items if it.id in set(res.saved)}
        for b in self.blocks:
            if b is block:
                b.items = [it for it in b.items if it.text not in saved]
        return res

    def retry_block(self, block, res):
        """Khối mới chỉ gồm các mục thiếu / hỏng của lần dán vừa rồi (đánh số lại từ 1)."""
        want = set(res.retry_ids)
        items = [it for it in block.items if it.id in want]
        return make_blocks(items, self.cfg, self.counter)

    def finish(self, log=print, progress=lambda d, t: None, file_progress=lambda d, t, r: None,
               should_stop=lambda: False):
        """Tạo file xlsx (+ md) từ cache. Chuỗi nào chưa có bản dịch giữ nguyên tiếng Nhật và được báo là lỗi."""
        if self.is_folder:
            return batch.process_folder(
                self.input, self.cfg, log=log, progress=progress, file_progress=file_progress,
                should_stop=should_stop, out_dir=self.out_dir, md_dir=self.md_dir,
            )
        out = self.out_dir or pipeline.default_out(self.input, self.cfg)
        return pipeline.process_xlsx(
            self.input, out, self.cfg, log=log, progress=progress, should_stop=should_stop, md_path=self.md_dir
        )


# ---- chế độ file (dùng cho CLI / Docker, không cần giao diện)
def export_blocks(session, directory):
    """Ghi block-001.txt (dán vào chat) và block-001.json (để nhập lại). Trả về số khối."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    blocks = session.scan() if not session.blocks else session.blocks
    for b in blocks:
        stem = d / f"block-{b.index:03d}"
        stem.with_suffix(".txt").write_text(b.prompt, encoding="utf-8")
        stem.with_suffix(".json").write_text(
            json.dumps(
                [{"id": i.id, "text": i.text, "masked": i.masked, "mapping": {str(k): v for k, v in i.mapping.items()}}
                 for i in b.items],
                ensure_ascii=False, indent=1,
            ),
            encoding="utf-8",
        )
    return len(blocks)


def import_blocks(session, directory, log=print):
    """Đọc block-NNN.out.txt (kết quả chat) cạnh block-NNN.json. Trả về (đã lưu, cần dán lại)."""
    d = Path(directory)
    if session.cache is None:
        session.scan()
    saved = redo = 0
    for jf in sorted(d.glob("block-*.json")):
        out = jf.with_name(jf.stem + ".out.txt")
        if not out.exists():
            continue
        items = [
            Item(r["id"], r["text"], r["masked"], {int(k): v for k, v in r["mapping"].items()})
            for r in json.loads(jf.read_text(encoding="utf-8"))
        ]
        block = Block(int(jf.stem.split("-")[1]), items, "", 0)
        session.blocks.append(block)
        res = session.apply_output(block, out.read_text(encoding="utf-8"))
        saved += len(res.saved)
        if res.retry_ids:
            redo += len(res.retry_ids)
            log(f"{out.name}: thiếu {res.missing}, lỗi {[f'{i}: {why}' for i, why in res.bad]}")
            retry = session.retry_block(block, res)
            for k, rb in enumerate(retry, 1):
                rb_stem = d / f"{jf.stem}-retry{k}"
                rb_stem.with_suffix(".txt").write_text(rb.prompt, encoding="utf-8")
                rb_stem.with_suffix(".json").write_text(
                    json.dumps(
                        [{"id": i.id, "text": i.text, "masked": i.masked,
                          "mapping": {str(a): b for a, b in i.mapping.items()}} for i in rb.items],
                        ensure_ascii=False, indent=1,
                    ),
                    encoding="utf-8",
                )
            log(f"  -> đã tạo {jf.stem}-retry*.txt cho các mục cần dán lại")
    return saved, redo
