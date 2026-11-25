"""Lịch sử các lượt dịch: mỗi file một dòng JSON trong history.jsonl (chỉ lưu trên máy, không có nội dung file)."""
import csv
import json
import threading
from datetime import datetime
from pathlib import Path

_lock = threading.Lock()

COLUMNS = ("time", "source", "backend", "model", "mode", "segments", "errors", "calls", "status",
           "prompt_tokens", "completion_tokens", "tps", "seconds", "exact")


def record(cfg, entry):
    """Ghi thêm một dòng; mọi lỗi I/O chỉ bị bỏ qua (lịch sử không được làm hỏng lượt dịch)."""
    if not getattr(cfg, "history_enabled", False):
        return
    entry = {"time": datetime.now().isoformat(timespec="seconds"), **entry}
    path = Path(cfg.history_file)
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _trim(path, cfg.history_max)
    except OSError:
        pass


def _trim(path, keep):
    if keep <= 0 or path.stat().st_size < keep * 120:  # chưa đủ lớn thì khỏi đọc lại
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > keep:
        path.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")


def load(path, limit=None):
    """Danh sách mục, MỚI NHẤT TRƯỚC. Bỏ qua dòng hỏng."""
    path = Path(path)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    out.reverse()
    return out[:limit] if limit else out


def clear(path):
    path = Path(path)
    if path.exists():
        path.unlink()


def summarize(entries):
    """Tổng hợp: số lượt, token vào/ra, tốc độ trung bình (tổng token ra / tổng giây sinh), tổng thời gian."""
    p = sum(e.get("prompt_tokens", 0) for e in entries)
    c = sum(e.get("completion_tokens", 0) for e in entries)
    timed = [e for e in entries if e.get("tps")]
    gen = sum(e["completion_tokens"] / e["tps"] for e in timed)
    done = sum(e["completion_tokens"] for e in timed)
    return {"runs": len(entries), "prompt_tokens": p, "completion_tokens": c,
            "tps": done / gen if gen > 0 else None, "seconds": sum(e.get("seconds", 0) for e in entries)}


def export_csv(entries, path):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # BOM để Excel đọc đúng tiếng Việt/Nhật
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(entries)


def fmt_tps(v):
    return f"{v:.1f}" if v else "—"


def fmt_seconds(s):
    s = int(round(s or 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"
