"""Dịch thủ công qua chat: copy từng khối vào chat, dán kết quả lại, rồi tạo file."""
import tkinter as tk
from tkinter import scrolledtext, ttk

from ..manual import ManualSession


class ManualDialog:
    def __init__(self, app, session: ManualSession):
        self.app, self.session = app, session
        self.pos = 0
        win = self.win = tk.Toplevel(app.root)
        win.title("Dịch thủ công qua chat")
        win.geometry("820x700")
        win.minsize(680, 520)
        win.transient(app.root)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(2, weight=1)
        win.rowconfigure(4, weight=1)

        self.head = tk.StringVar()
        self.status = tk.StringVar()
        ttk.Label(win, textvariable=self.head, style="Heading.TLabel", padding=(14, 12, 14, 0)).grid(row=0, column=0, sticky="w")
        self.bar = ttk.Progressbar(win, mode="determinate")
        self.bar.grid(row=1, column=0, sticky="ew", padx=14, pady=(6, 8))

        self.prompt_box = scrolledtext.ScrolledText(win, height=10, wrap="word", state="disabled", font=("Consolas", 10))
        self.prompt_box.grid(row=2, column=0, sticky="nsew", padx=14)
        bar1 = ttk.Frame(win, padding=(14, 6))
        bar1.grid(row=3, column=0, sticky="ew")
        ttk.Button(bar1, text="1) Copy khối này", style="Accent.TButton", command=self.copy_block).pack(side="left")
        ttk.Button(bar1, text="◀", width=3, command=lambda: self.move(-1)).pack(side="left", padx=(14, 2))
        ttk.Button(bar1, text="▶", width=3, command=lambda: self.move(1)).pack(side="left")
        ttk.Label(bar1, text="  2) Dán câu trả lời của chat vào ô dưới", style="Hint.TLabel").pack(side="left", padx=10)

        self.result_box = scrolledtext.ScrolledText(win, height=10, wrap="word", font=("Consolas", 10))
        self.result_box.grid(row=4, column=0, sticky="nsew", padx=14)
        ttk.Label(win, textvariable=self.status, wraplength=780, style="Hint.TLabel").grid(row=5, column=0, sticky="w", padx=14, pady=6)
        bar2 = ttk.Frame(win, padding=(14, 0, 14, 12))
        bar2.grid(row=6, column=0, sticky="ew")
        ttk.Button(bar2, text="3) Lưu kết quả của khối này", command=self.save_result).pack(side="left")
        ttk.Button(bar2, text="Tạo file xlsx / md từ bản dịch đã có", style="Accent.TButton", command=self.finish).pack(side="right")
        ttk.Button(bar2, text="Đóng", command=win.destroy).pack(side="right", padx=8)
        self.refresh()

    def current(self):
        b = self.session.blocks
        return b[self.pos] if b else None

    def refresh(self):
        s = self.session
        n = len(s.blocks)
        self.pos = min(self.pos, max(n - 1, 0))
        b = self.current()
        done = s.done_count()
        self.bar.configure(maximum=max(s.total, 1), value=done)
        for box in (self.prompt_box,):
            box.configure(state="normal")
            box.delete("1.0", "end")
        self.result_box.delete("1.0", "end")
        if b:
            self.head.set(f"Khối {self.pos + 1}/{n} · {len(b.items)} mục · {b.tokens} token ({s.counter.kind}) · "
                          f"đã có {done}/{s.total} bản dịch")
            self.prompt_box.insert("1.0", b.prompt)
        else:
            self.head.set(f"Hết khối cần dịch · đã có {done}/{s.total} bản dịch — bấm “Tạo file”.")
        self.prompt_box.configure(state="disabled")

    def copy_block(self):
        b = self.current()
        if b:
            self.win.clipboard_clear()
            self.win.clipboard_append(b.prompt)
            self.status.set("Đã copy khối vào clipboard. Dán vào chat, chờ kết quả rồi dán vào ô bên dưới.")

    def move(self, d):
        if self.session.blocks:
            self.pos = (self.pos + d) % len(self.session.blocks)
            self.refresh()

    def save_result(self):
        b = self.current()
        if not b:
            return
        text = self.result_box.get("1.0", "end-1c")
        if not text.strip():
            self.status.set("Ô kết quả đang trống.")
            return
        res = self.session.apply_output(b, text)
        msg = f"Đã lưu {len(res.saved)} bản dịch."
        if res.suspect:
            msg += f" {len(res.suspect)} mục vẫn còn tiếng Nhật (chat có thể chưa dịch): {res.suspect}."
        if res.extra:
            msg += f" Bỏ qua {res.extra} dòng có số không thuộc khối này."
        retry = self.session.retry_block(b, res) if res.retry_ids else []
        if res.missing:
            msg += f" Thiếu mục {res.missing}."
        if res.bad:
            msg += " Lỗi: " + "; ".join(f"{i} ({why})" for i, why in res.bad) + "."
        self.session.blocks[self.pos:self.pos + 1] = retry  # khối xong thì bỏ; còn mục thiếu/hỏng thì thay bằng khối mới
        if retry:
            msg += " Khối mới chỉ gồm các mục này đã thay vào chỗ khối cũ — copy và hỏi lại chat."
        self.refresh()
        self.status.set(msg)

    def finish(self):
        self.win.destroy()
        self.app.run_job("Tạo file từ bản dịch thủ công", lambda cb: self.app.finish_manual(self.session, cb))
