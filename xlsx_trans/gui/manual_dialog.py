"""Dịch thủ công qua chat: copy từng khối vào chat, dán kết quả lại, rồi tạo file."""
import tkinter as tk
from tkinter import scrolledtext, ttk

from ..manual import ManualSession


class ManualDialog:
    def __init__(self, app, session: ManualSession):
        self.app, self.session = app, session
        self.pos = 0
        self.texts = {}  # id(block) -> văn bản kết quả đã dán
        self.sizes = {}  # số mục ban đầu của khối (apply_output bỏ dần mục đã lưu)
        self.state = {}  # id(block) -> 'done' | 'partial'
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
        ttk.Button(bar1, text="2) Dán từ clipboard", command=self.paste_result).pack(side="right")
        ttk.Label(bar1, text="  Dán câu trả lời của chat vào ô dưới", style="Hint.TLabel").pack(side="left", padx=10)

        self.result_box = scrolledtext.ScrolledText(win, height=10, wrap="word", font=("Consolas", 10))
        self.result_box.grid(row=4, column=0, sticky="nsew", padx=14)
        ttk.Label(win, textvariable=self.status, wraplength=780, style="Hint.TLabel").grid(row=5, column=0, sticky="w", padx=14, pady=6)
        bar2 = ttk.Frame(win, padding=(14, 0, 14, 12))
        bar2.grid(row=6, column=0, sticky="ew")
        ttk.Button(bar2, text="3) Lưu kết quả của khối này", command=self.save_result).pack(side="left")
        ttk.Button(bar2, text="Tạo file xlsx / md từ bản dịch đã có", style="Accent.TButton", command=self.finish).pack(side="right")
        ttk.Button(bar2, text="Đóng", command=win.destroy).pack(side="right", padx=8)
        for seq in ("<Control-v>", "<Control-V>", "<Shift-Insert>"):
            win.bind(seq, self._ctrl_v)
        self.prompt_box.bind("<<Paste>>", lambda e: self.paste_result())  # ô prompt chỉ để copy, dán luôn chuyển sang ô kết quả
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
            done_blk = self.state.get(id(b)) == "done"
            mark = "  ✔ ĐÃ LƯU" if done_blk else ""
            shown = self.sizes.get(id(b), len(b.items)) if done_blk else len(b.items)
            self.head.set(f"Khối {self.pos + 1}/{n} · {shown} mục · {b.tokens} token ({getattr(s.counter, "kind", "?")}) · "
                          f"đã có {done}/{s.total} bản dịch{mark}")
            self.prompt_box.insert("1.0", b.prompt)
            self.result_box.insert("1.0", self.texts.get(id(b), ""))
            if not done_blk:
                self.result_box.focus_set()
        else:
            self.head.set(f"Hết khối cần dịch · đã có {done}/{s.total} bản dịch — bấm “Tạo file”.")
        self.prompt_box.configure(state="disabled")

    def copy_block(self):
        b = self.current()
        if b:
            self.win.clipboard_clear()
            self.win.clipboard_append(b.prompt)
            self.result_box.focus_set()
            self.status.set("Đã copy khối vào clipboard. Dán vào chat, chờ kết quả, copy câu trả lời rồi bấm “Dán từ clipboard”.")

    def move(self, d):
        if self.session.blocks:
            self.pos = (self.pos + d) % len(self.session.blocks)
            self.refresh()

    def paste_result(self):
        """Dán clipboard vào ô kết quả (thay toàn bộ nội dung cũ) và đưa con trỏ về ô đó."""
        try:
            text = self.win.clipboard_get()
        except tk.TclError:
            self.status.set("Clipboard đang trống (hoặc không phải chữ). Hãy copy câu trả lời của chat trước.")
            return "break"
        self.result_box.delete("1.0", "end")
        self.result_box.insert("1.0", text)
        self.result_box.focus_set()
        self.status.set(f"Đã dán {len(text.splitlines())} dòng vào ô kết quả. Bấm “3) Lưu kết quả của khối này”.")
        return "break"

    def _ctrl_v(self, event):
        """Ctrl+V ở bất cứ đâu trong cửa sổ đều dán vào ô kết quả (không bao giờ vào ô prompt)."""
        if self.win.focus_get() is self.result_box:
            return None  # ô kết quả tự dán theo mặc định, tránh dán hai lần
        return self.paste_result()

    def save_result(self):
        b = self.current()
        if not b:
            return
        if self.state.get(id(b)) == "done":
            self.status.set("Khối này đã lưu xong. Bấm ▶ sang khối khác, hoặc “Tạo file” nếu đã hết khối.")
            return
        text = self.result_box.get("1.0", "end-1c")
        if not text.strip():
            self.status.set("Ô kết quả đang trống. Copy câu trả lời của chat rồi bấm “Dán từ clipboard”.")
            return
        self.sizes.setdefault(id(b), len(b.items))
        res = self.session.apply_output(b, text)
        if not res.saved:
            why = ("; ".join(f"{i} ({w})" for i, w in res.bad) if res.bad else
                   "không thấy dòng nào dạng “[số] bản dịch” — kiểm tra đã dán đúng câu trả lời của chat (không phải prompt)")
            self.status.set(f"Chưa lưu được mục nào: {why}. Khối giữ nguyên, có thể dán lại.")
            return
        msg = f"Đã lưu {len(res.saved)} bản dịch."
        if res.suspect:
            msg += f" {len(res.suspect)} mục vẫn còn tiếng Nhật (chat có thể chưa dịch): {res.suspect}."
        if res.extra:
            msg += f" Bỏ qua {res.extra} dòng có số không thuộc khối này."
        if res.missing:
            msg += f" Thiếu mục {res.missing}."
        if res.bad:
            msg += " Lỗi: " + "; ".join(f"{i} ({why})" for i, why in res.bad) + "."
        if b.items:  # còn mục thiếu/hỏng: rút gọn chính khối này, không thêm khối mới
            self.session.shrink_block(b)
            self.texts.pop(id(b), None)
            self.refresh()
            self.status.set(f"✔ {msg} Khối này đã rút gọn còn {len(b.items)} mục chưa dịch (đánh số lại từ 1) — "
                            "bấm “1) Copy khối này” và hỏi lại chat.")
            return
        self.texts[id(b)] = text
        self.state[id(b)] = "done"
        self.pos = self._next_pending(self.pos)
        self.refresh()
        if all(id(x) in self.state for x in self.session.blocks):
            msg += " Đã hết khối — bấm “Tạo file xlsx / md”."
        self.status.set("✔ " + msg)

    def _next_pending(self, start):
        bl = self.session.blocks
        for k in range(1, len(bl) + 1):
            i = (start + k) % len(bl)
            if id(bl[i]) not in self.state:
                return i
        return start

    def finish(self):
        self.win.destroy()
        self.app.run_job("Tạo file từ bản dịch thủ công", lambda cb: self.app.finish_manual(self.session, cb))
