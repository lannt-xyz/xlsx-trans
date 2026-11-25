"""Trình sửa từ điển và hộp thoại duyệt gợi ý danh từ riêng."""
import tkinter as tk
from tkinter import messagebox, ttk

from .. import dictionary as dic


class DictionaryDialog:
    """Danh sách từ giữ nguyên tiếng Nhật: tìm, lọc theo nhóm, thêm, dán nhiều dòng, xóa."""

    ALL = "(tất cả nhóm)"

    def __init__(self, app):
        self.app = app
        self.path = app.cfg.dict_files[0]
        self.entries = dic.Dictionary.load([self.path]).entries
        self.dirty = False
        win = self.win = tk.Toplevel(app.root)
        win.title(f"Từ điển giữ nguyên tiếng Nhật — {self.path.name}")
        win.geometry("700x560")
        win.minsize(560, 420)
        win.transient(app.root)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)

        top = ttk.Frame(win, padding=(12, 12, 12, 4))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *_: self.refresh())
        ttk.Entry(top, textvariable=self.q).grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="Tìm…", style="Hint.TLabel").grid(row=1, column=0, sticky="w")
        self.cat_filter = tk.StringVar(value=self.ALL)
        self.filter_box = ttk.Combobox(top, textvariable=self.cat_filter, state="readonly", width=22)
        self.filter_box.grid(row=0, column=1, padx=(8, 0))
        self.filter_box.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        mid = ttk.Frame(win, padding=(12, 0))
        mid.grid(row=1, column=0, sticky="nsew")
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(mid, columns=("term", "cat"), show="headings", selectmode="extended")
        self.tree.heading("term", text="Từ")
        self.tree.heading("cat", text="Nhóm")
        self.tree.column("term", width=420)
        self.tree.column("cat", width=140)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Delete>", lambda e: self.delete())

        add = ttk.Frame(win, padding=(12, 8, 12, 0))
        add.grid(row=2, column=0, sticky="ew")
        add.columnconfigure(0, weight=1)
        self.new_term = tk.StringVar()
        self.new_cat = tk.StringVar(value="other")
        e = ttk.Entry(add, textvariable=self.new_term)
        e.grid(row=0, column=0, sticky="ew")
        e.bind("<Return>", lambda ev: self.add())
        self.cat_box = ttk.Combobox(add, textvariable=self.new_cat, width=16)
        self.cat_box.grid(row=0, column=1, padx=6)
        ttk.Button(add, text="Thêm", command=self.add).grid(row=0, column=2)
        ttk.Button(add, text="Dán nhiều dòng…", command=self.paste_many).grid(row=0, column=3, padx=(6, 0))

        self.status = tk.StringVar()
        ttk.Label(win, textvariable=self.status, style="Hint.TLabel").grid(row=3, column=0, sticky="w", padx=14, pady=(6, 0))
        bar = ttk.Frame(win, padding=12)
        bar.grid(row=4, column=0, sticky="ew")
        ttk.Button(bar, text="Xóa đã chọn", command=self.delete).pack(side="left")
        ttk.Button(bar, text="Lưu", style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(bar, text="Đóng", command=self.close).pack(side="right", padx=6)
        win.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        e.focus_set()

    def cats(self):
        return list(self.entries) or ["other"]

    def refresh(self):
        q = self.q.get().strip()
        cat = self.cat_filter.get()
        self.filter_box["values"] = [self.ALL] + self.cats()
        self.cat_box["values"] = self.cats()
        self.tree.delete(*self.tree.get_children())
        n = 0
        for c, terms in self.entries.items():
            if cat not in (self.ALL, c):
                continue
            for t in terms:
                if q and q not in t:
                    continue
                self.tree.insert("", "end", values=(t, c))
                n += 1
        total = sum(len(v) for v in self.entries.values())
        self.status.set(f"{n} từ hiển thị / {total} từ" + ("  •  có thay đổi chưa lưu" if self.dirty else ""))

    def _add(self, term, cat):
        term, cat = term.strip(), (cat.strip() or "other")
        if not term or "\n" in term or (term.startswith("[") and term.endswith("]")):
            return False
        bucket = self.entries.setdefault(cat, [])
        if term in bucket:
            return False
        bucket.append(term)
        self.dirty = True
        return True

    def add(self):
        if self._add(self.new_term.get(), self.new_cat.get()):
            self.new_term.set("")
        self.refresh()

    def paste_many(self):
        top = tk.Toplevel(self.win)
        top.title("Dán nhiều từ")
        top.transient(self.win)
        ttk.Label(top, text="Mỗi dòng một từ — sẽ thêm vào nhóm đang chọn ở ô nhóm:", padding=8).pack(anchor="w")
        box = tk.Text(top, width=48, height=14)
        box.pack(fill="both", expand=True, padx=8)

        def ok():
            added = sum(self._add(line, self.new_cat.get()) for line in box.get("1.0", "end-1c").splitlines())
            top.destroy()
            self.refresh()
            self.status.set(f"Đã thêm {added} từ (chưa lưu).")

        ttk.Button(top, text="Thêm", style="Accent.TButton", command=ok).pack(pady=8)
        box.focus_set()

    def delete(self):
        for item in self.tree.selection():
            term, cat = self.tree.item(item, "values")
            if term in self.entries.get(cat, []):
                self.entries[cat].remove(term)
                self.dirty = True
        self.refresh()

    def save(self):
        try:
            dic.write_entries(self.path, self.entries)
        except OSError as e:
            messagebox.showerror("Lỗi khi lưu", str(e), parent=self.win)
            return
        self.dirty = False
        self.app.cfg.reload_dictionary()
        self.app.on_settings_changed(f"Đã lưu từ điển ({len(self.app.cfg.dictionary)} từ).")
        self.refresh()

    def close(self):
        if self.dirty and not messagebox.askyesno("Từ điển", "Bỏ các thay đổi chưa lưu?", parent=self.win):
            return
        self.win.destroy()


class ReviewDialog:
    """Gợi ý danh từ riêng chưa có trong từ điển. run() chặn cho tới khi người dùng chọn; trả về {term: "add"|"ignore"}."""

    def __init__(self, app, cands):
        self.cands, self.result = cands, {}
        win = self.win = tk.Toplevel(app.root)
        win.title("Gợi ý thêm vào từ điển (giữ nguyên tiếng Nhật)")
        win.geometry("760x520")
        win.transient(app.root)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        ttk.Label(
            win, wraplength=720, padding=(12, 12, 12, 6),
            text=f"{len(cands)} từ có vẻ là danh từ riêng (tên người, màn hình, nút, message…) và chưa có trong từ điển. "
            "Chọn những từ cần GIỮ NGUYÊN tiếng Nhật (Ctrl/Shift để chọn nhiều).",
        ).grid(row=0, column=0, sticky="ew")
        mid = ttk.Frame(win, padding=(12, 0))
        mid.grid(row=1, column=0, sticky="nsew")
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(0, weight=1)
        cols = ("term", "cat", "n", "ex")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended")
        for c, t, w in (("term", "Từ", 200), ("cat", "Loại", 80), ("n", "Số lần", 60), ("ex", "Ví dụ trong file", 320)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        for i, c in enumerate(cands):
            self.tree.insert("", "end", iid=str(i), values=(c.term, c.category, c.count, c.example))
        bar = ttk.Frame(win, padding=12)
        bar.grid(row=2, column=0, sticky="ew")
        ttk.Button(bar, text="Chọn tất cả", command=lambda: self.tree.selection_set(self.tree.get_children())).pack(side="left")
        ttk.Button(bar, text="Bỏ chọn", command=lambda: self.tree.selection_remove(self.tree.get_children())).pack(side="left", padx=6)
        ttk.Button(bar, text="Thêm các từ đã chọn", style="Accent.TButton", command=lambda: self.finish("add")).pack(side="right")
        ttk.Button(bar, text="Thêm đã chọn, không hỏi lại các từ còn lại", command=lambda: self.finish("never")).pack(side="right", padx=6)
        ttk.Button(bar, text="Bỏ qua lần này", command=self.skip).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", self.skip)
        win.grab_set()

    def finish(self, mode):
        chosen = {int(i) for i in self.tree.selection()}
        for i, c in enumerate(self.cands):
            if i in chosen:
                self.result[c.term] = "add"
            elif mode == "never":
                self.result[c.term] = "ignore"
        self.win.destroy()

    def skip(self):
        self.result.clear()
        self.win.destroy()

    def run(self):
        self.win.wait_window()
        return self.result
