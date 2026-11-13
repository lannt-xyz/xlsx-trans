"""Cửa sổ lịch sử dịch: model, token vào/ra, tốc độ (tok/s), thời gian."""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import history
from .util import open_path

STATUS = {"done": "Xong", "partial": "Có lỗi", "stopped": "Đã dừng", "error": "Lỗi"}
COLS = (
    ("time", "Thời gian", 140, "w"), ("file", "File", 230, "w"), ("model", "Model", 190, "w"),
    ("pin", "Token vào", 80, "e"), ("pout", "Token ra", 80, "e"), ("tps", "tok/s", 60, "e"),
    ("dur", "Thời gian chạy", 90, "e"), ("seg", "Đoạn dịch", 70, "e"), ("err", "Lỗi", 45, "e"), ("status", "Kết quả", 80, "w"),
)


class HistoryDialog:
    def __init__(self, app):
        self.app = app
        self.path = app.cfg.history_file
        self.entries = []
        win = self.win = tk.Toplevel(app.root)
        win.title("Lịch sử dịch")
        win.geometry("1060x520")
        win.minsize(760, 360)
        win.transient(app.root)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)

        self.summary = tk.StringVar()
        ttk.Label(win, textvariable=self.summary, padding=(12, 10, 12, 4)).grid(row=0, column=0, sticky="ew")

        mid = ttk.Frame(win, padding=(12, 0))
        mid.grid(row=1, column=0, sticky="nsew")
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(mid, columns=[c[0] for c in COLS], show="headings", selectmode="browse")
        for key, title, width, anchor in COLS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor, stretch=key in ("file", "model"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.tag_configure("bad", foreground=app.pal["err"])
        self.tree.tag_configure("warn", foreground=app.pal["warn"])

        self.note = tk.StringVar()
        ttk.Label(win, textvariable=self.note, style="Hint.TLabel", padding=(12, 4, 12, 0)).grid(row=2, column=0, sticky="w")
        bar = ttk.Frame(win, padding=12)
        bar.grid(row=3, column=0, sticky="ew")
        bar.columnconfigure(3, weight=1)
        ttk.Button(bar, text="Làm mới", command=self.load).grid(row=0, column=0)
        ttk.Button(bar, text="Xuất CSV…", command=self.export).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(bar, text="Mở file lịch sử", command=self.open_file).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(bar, text="Xóa lịch sử", command=self.clear).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(bar, text="Đóng", command=win.destroy).grid(row=0, column=5)
        self.load()

    def load(self):
        self.entries = history.load(self.path)
        self.tree.delete(*self.tree.get_children())
        for e in self.entries:
            from pathlib import Path

            exact = e.get("exact", True)
            mark = "" if exact else "~"
            tag = "bad" if e.get("status") == "error" else "warn" if e.get("status") in ("partial", "stopped") else ""
            self.tree.insert("", "end", tags=(tag,), values=(
                str(e.get("time", "")).replace("T", " "), Path(str(e.get("source", ""))).name,
                f"{e.get('model', '')}" + ("" if e.get("backend") in (None, "ollama") else f" ({e.get('backend')})"),
                f"{mark}{e.get('prompt_tokens', 0):,}", f"{mark}{e.get('completion_tokens', 0):,}", history.fmt_tps(e.get("tps")),
                history.fmt_seconds(e.get("seconds")), e.get("segments", 0), e.get("errors", 0),
                STATUS.get(e.get("status"), e.get("status", "")),
            ))
        s = history.summarize(self.entries)
        if not self.entries:
            self.summary.set("Chưa có lượt dịch nào." if self.app.cfg.history_enabled else
                             "Lịch sử đang tắt (Cài đặt → Đầu ra → Ghi lịch sử dịch).")
        else:
            self.summary.set(f"{s['runs']} lượt · {s['prompt_tokens']:,} token vào · {s['completion_tokens']:,} token ra · "
                             f"tốc độ trung bình {history.fmt_tps(s['tps'])} tok/s · tổng {history.fmt_seconds(s['seconds'])}")
        self.note.set("tok/s = token đầu ra / thời gian sinh (Ollama đo chính xác; llama.cpp tính cả thời gian đọc prompt). "
                      "Dấu ~ = ước lượng (chế độ thủ công). Lượt chỉ dùng cache thì không có token." if self.entries else "")

    def export(self):
        if not self.entries:
            return
        p = filedialog.asksaveasfilename(parent=self.win, defaultextension=".csv", initialfile="lich_su_dich.csv",
                                         filetypes=[("CSV", "*.csv")])
        if p:
            history.export_csv(self.entries, p)
            self.app.status_var.set(f"Đã xuất lịch sử: {p}")

    def open_file(self):
        if self.path.exists():
            open_path(self.path.parent)
        else:
            messagebox.showinfo("Lịch sử", "Chưa có file lịch sử.", parent=self.win)

    def clear(self):
        if self.entries and messagebox.askyesno("Xóa lịch sử", "Xóa toàn bộ lịch sử dịch?", parent=self.win):
            history.clear(self.path)
            self.load()
