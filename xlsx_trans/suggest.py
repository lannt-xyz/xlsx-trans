"""Gợi ý danh từ riêng chưa có trong từ điển để người dùng duyệt rồi thêm (không dùng model).

Chỉ là heuristic nên sẽ có gợi ý sai/thiếu; người dùng quyết định từng từ:
  person   「山田太郎さん」 -> 山田太郎 (đuôi さん/様/氏/殿/君...)
  screen   ô ngắn kiểu 「ログイン画面」「受注一覧」「顧客登録」 (đuôi 画面/一覧/登録/詳細/管理...)
  label    chữ trong 「」『』【】 (tên nút, tên màn hình, tên mục được nhắc trong câu)
  message  ô ngắn kiểu thông báo 「保存しました。」「エラーが発生しました」
  item     ô chỉ gồm katakana (thường là tên sản phẩm/mục: 「ステータス」...), ưu tiên thấp nhất
"""
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .dictionary import add_term

SCREEN_SUFFIX = (
    "画面|一覧|登録|詳細|管理|入力|確認|検索|編集|変更|削除|照会|メニュー|ポップアップ|ダイアログ|フォーム|ページ|ボタン|タブ|設定"
)
MESSAGE_WORDS = "しました|できません|ありません|してください|ください|エラー|失敗|成功|完了|不正|存在しません"
HONORIFIC = "さん|様|氏|殿|君|くん|ちゃん"
NAME_CHARS = "一-鿿ァ-ヶー々"

RE_PERSON = re.compile(rf"([{NAME_CHARS}]{{2,6}})(?:{HONORIFIC})")
RE_QUOTED = re.compile(r"[「『【]([^「」『』【】\n]{2,20})[」』】]")
RE_SCREEN = re.compile(rf"^[^\s。、，．！？!?「」『』【】()（）]{{2,18}}(?:{SCREEN_SUFFIX})$")
RE_KATAKANA = re.compile(r"^[ァ-ヶー・]{3,}$")
RE_MESSAGE = re.compile(rf"(?:{MESSAGE_WORDS})")
RE_HIRAGANA = re.compile(r"[ぁ-ん]")
NOT_A_NAME = re.compile(r"担当|責任|管理|各|貴|皆|お客|顧客|ご|お|本人|ユーザ")

PRIORITY = {"person": 0, "screen": 1, "label": 2, "message": 3, "item": 4}


@dataclass
class Candidate:
    term: str
    category: str
    count: int
    example: str


def _detect(text):
    """[(term, category, số lần)] tìm thấy trong một đoạn chữ."""
    found = []
    t = text.strip()
    if "\n" not in t:
        if RE_SCREEN.match(t) and not RE_HIRAGANA.search(t.lstrip("おご")):
            found.append((t, "screen", 1))
        elif RE_KATAKANA.match(t):
            found.append((t, "item", 1))
        elif len(t) <= 40 and RE_MESSAGE.search(t) and ("。" in t or "！" in t or len(t) <= 25):
            found.append((t, "message", 1))
    for m in RE_PERSON.finditer(text):
        name = m.group(1)
        if not NOT_A_NAME.search(name):
            found.append((name, "person", 1))
    for m in RE_QUOTED.finditer(text):
        inner = m.group(1).strip()
        if "。" not in inner and not inner.isdigit():
            found.append((inner, "label", 1))
    return found


def suggest(texts, dictionary, src_re, ignored=(), limit=50):
    """Danh sách Candidate (đã loại từ có trong từ điển / danh sách bỏ qua), ưu tiên theo loại rồi số lần xuất hiện."""
    known = set(dictionary.terms()) if dictionary else set()
    ignored = set(ignored)
    count, cat, example = Counter(), {}, {}
    for text in texts:
        for term, c, n in _detect(text):
            if term in known or term in ignored or not src_re.search(term):
                continue
            if dictionary and not dictionary.needs_translation(term, src_re):
                continue  # đã được từ điển phủ trọn (ghép từ nhiều từ có sẵn)
            count[term] += n
            if term not in cat or PRIORITY[c] < PRIORITY[cat[term]]:
                cat[term] = c
            example.setdefault(term, text.strip().replace("\n", " ")[:40])
    cands = [Candidate(t, cat[t], n, example[t]) for t, n in count.items()]
    cands.sort(key=lambda c: (PRIORITY[c.category], -c.count, c.term))
    return cands[:limit] if limit else cands


# ---- danh sách "không hỏi lại"
def load_ignored(path):
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return set()
    return {l.strip() for l in lines if l.strip() and not l.strip().startswith("#")}


def add_ignored(path, terms):
    terms = [t for t in terms if t.strip()]
    if not terms:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + "\n".join(terms) + "\n", encoding="utf-8")


def review_texts(texts, cfg, review, log=print):
    """Gợi ý -> hỏi người dùng qua `review(candidates) -> {term: "add" | "ignore"}` -> cập nhật từ điển.

    review=None, tắt gợi ý hoặc tắt từ điển thì không làm gì. Trả về số từ đã thêm.
    """
    if review is None or not cfg.suggest or not cfg.dict_enabled:
        return 0
    cands = suggest(texts, cfg.dictionary, cfg.src_re, cfg.ignored, cfg.suggest_max)
    if not cands:
        return 0
    log(f"Gợi ý từ điển: {len(cands)} từ có vẻ là danh từ riêng và chưa có trong từ điển.")
    decision = review(cands) or {}
    added, ignore = 0, []
    for c in cands:
        d = decision.get(c.term)
        if d == "add":
            if add_term(cfg.dict_files[0], c.category, c.term):
                added += 1
        elif d == "ignore":
            ignore.append(c.term)
    add_ignored(cfg.dict_ignore_file, ignore)
    if added or ignore:
        cfg.reload_dictionary()
        log(f"Từ điển: đã thêm {added} từ, bỏ qua vĩnh viễn {len(ignore)} từ.")
    return added
