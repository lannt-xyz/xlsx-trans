"""Widget dùng chung: Card, Stat, LogView."""
import tkinter as tk
from tkinter import ttk

from .util import classify_log


class Card(ttk.Frame):
    """Khung nội dung có tiêu đề; `.body` là nơi đặt widget."""

    def __init__(self, parent, title=None, **kw):
        try:
            super().__init__(parent, style="Card.TFrame", padding=14, **kw)
        except tk.TclError:
            super().__init__(parent, padding=14, **kw)
        self.columnconfigure(0, weight=1)
        r = 0
        if title:
            ttk.Label(self, text=title, style="Heading.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
            r = 1
        self.body = ttk.Frame(self)
        self.body.grid(row=r, column=0, sticky="nsew")
        self.rowconfigure(r, weight=1)


class Stat(ttk.Frame):
    """Một ô số liệu: giá trị lớn + nhãn nhỏ."""

    def __init__(self, parent, label):
        super().__init__(parent)
        self.value = tk.StringVar(value="—")
        self.label = ttk.Label(self, textvariable=self.value, font=("Segoe UI", 13, "bold"))
        self.label.pack(anchor="w")
        ttk.Label(self, text=label, style="Hint.TLabel").pack(anchor="w")

    def set(self, text, style=None):
        self.value.set(text)
        self.label.configure(style=style or "TLabel")


class LogView(ttk.Frame):
    """Hộp log tô màu theo mức; có thanh cuộn, copy và xóa."""

    def __init__(self, parent, palette, height=10):
        super().__init__(parent)
        self.text = tk.Text(self, height=height, wrap="word", state="disabled", relief="flat", borderwidth=0,
                            padx=10, pady=8, font=("Consolas", 10))
        sb = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.restyle(palette)

    def restyle(self, pal):
        self.text.configure(background=pal["log_bg"], foreground=pal["fg"], insertbackground=pal["fg"],
                            selectbackground=pal["sel"], highlightthickness=1, highlightbackground=pal["border"],
                            highlightcolor=pal["border"])
        self.text.tag_configure("error", foreground=pal["err"])
        self.text.tag_configure("warn", foreground=pal["warn"])
        self.text.tag_configure("ok", foreground=pal["ok"])
        self.text.tag_configure("info", foreground=pal["fg"])
        self.text.tag_configure("muted", foreground=pal["muted"])

    def add(self, line):
        level = classify_log(line)
        at_bottom = self.text.yview()[1] >= 0.999
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n", level)
        # giữ log không phình mãi khi dịch folder lớn
        if int(self.text.index("end-1c").split(".")[0]) > 5000:
            self.text.delete("1.0", "1000.0")
        self.text.configure(state="disabled")
        if at_bottom:
            self.text.see("end")
        return level

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def contents(self):
        return self.text.get("1.0", "end-1c")
