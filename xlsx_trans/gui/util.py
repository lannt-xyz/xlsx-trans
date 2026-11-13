"""Hàm thuần (không cần tkinter) dùng cho giao diện."""
import os
import subprocess
import sys
from pathlib import Path


def format_duration(seconds):
    """83 -> '01:23'; 3700 -> '1:01:40'."""
    s = max(int(seconds), 0)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def classify_log(line):
    """Mức của một dòng log để tô màu: error | warn | ok | info."""
    t = line.strip()
    if t.startswith(("LỖI", "Lỗi")) or "Lỗi với đoạn" in t or t.startswith("FAILED"):
        return "error"
    if t.startswith(("Cảnh báo", "(Có ")) or "Đã dừng" in t or "dừng" in t.split(":")[0].lower():
        return "warn"
    if t.startswith(("Xong", "Hoàn tất", "Đã lưu", "Đã xuất", "Từ điển: đã thêm")):
        return "ok"
    return "info"


def estimate_eta(elapsed, files_done, files_total, unit_fraction):
    """Ước lượng thời gian còn lại (giây) hoặc None nếu chưa đủ dữ liệu.

    files_done / files_total: tiến độ theo file (files_total=1 cho một file); unit_fraction: phần đã xong của file hiện tại.
    """
    if files_total <= 0:
        return None
    progress = (files_done + max(min(unit_fraction, 1.0), 0.0)) / files_total
    if progress < 0.02 or elapsed < 3:
        return None
    return max(elapsed / progress - elapsed, 0.0)


def open_path(path):
    """Mở file/thư mục bằng ứng dụng mặc định của hệ điều hành. Trả về True nếu gọi được."""
    p = str(Path(path))
    try:
        if sys.platform.startswith("win"):
            os.startfile(p)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
        return True
    except OSError:
        return False
