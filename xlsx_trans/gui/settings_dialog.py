"""Hộp thoại Cài đặt: mọi tùy chọn của config.toml chia theo tab, có kiểm tra giá trị, áp dụng tạm hoặc lưu vào config.local.toml."""
import copy
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .. import config as cfgmod
from ..ollama import list_models
from . import settings_model as sm

PROMPT_TAB = "Prompt"


class SettingsDialog:
    def __init__(self, app, start_tab=None):
        self.app = app
        self.cfg = app.cfg
        self.initial = sm.read_values(self.cfg)
        self.vars = {}
        self.entries = {}
        win = self.win = tk.Toplevel(app.root)
        win.title("Cài đặt")
        win.geometry("760x640")
        win.minsize(680, 520)
        win.transient(app.root)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

        self.nb = ttk.Notebook(win)
        self.nb.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))
        self.tab_frames = {}
        for tab in sm.TAB_ORDER:
            self.tab_frames[tab] = self._build_tab(tab)
        self.tab_frames[PROMPT_TAB] = self._build_prompt_tab()
        self.nb.select(self.tab_frames.get(start_tab, self.tab_frames[sm.TAB_ORDER[0]]))

        self.msg = tk.StringVar()
        ttk.Label(win, textvariable=self.msg, style="Err.TLabel", wraplength=700).grid(row=1, column=0, sticky="w", padx=14)
        bar = ttk.Frame(win)
        bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 12))
        ttk.Button(bar, text="Khôi phục mặc định", command=self.reset).pack(side="left")
        ttk.Button(bar, text="Lưu", style="Accent.TButton", command=lambda: self.commit(persist=True)).pack(side="right")
        ttk.Button(bar, text="Áp dụng (chỉ phiên này)", command=lambda: self.commit(persist=False)).pack(side="right", padx=6)
        ttk.Button(bar, text="Hủy", command=win.destroy).pack(side="right")
        win.bind("<Escape>", lambda e: win.destroy())
        win.grab_set()

    # ---- dựng tab
    def _scrollable(self, tab):
        outer = ttk.Frame(self.nb)
        self.nb.add(outer, text=tab)
        canvas = tk.Canvas(outer, highlightthickness=0, background=self.app.pal["bg"])
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(16, 10))
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        inner.columnconfigure(1, weight=1)
        return outer, inner

    def _build_tab(self, tab):
        outer, inner = self._scrollable(tab)
        row, group = 0, None
        for f in sm.fields_of(tab):
            if f.group != group:
                group = f.group
                ttk.Label(inner, text=group, style="Heading.TLabel").grid(
                    row=row, column=0, columnspan=3, sticky="w", pady=(12 if row else 0, 4))
                row += 1
            row = self._add_field(inner, row, f)
        if tab == "Mô hình":
            row = self._model_extras(inner, row)
        if tab == "Từ điển":
            self._dictionary_extras(inner, row)
        return outer

    def _add_field(self, parent, row, f):
        v = self.initial[f.key]
        if f.kind == "bool":
            var = tk.BooleanVar(value=bool(v))
            ttk.Checkbutton(parent, text=f.label, variable=var).grid(row=row, column=0, columnspan=3, sticky="w", pady=3)
        else:
            ttk.Label(parent, text=f.label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
            var = tk.StringVar(value=sm.to_text(f, v))
            if f.kind == "choice":
                w = ttk.Combobox(parent, textvariable=var, values=f.choices, state="readonly", width=24)
            else:
                w = ttk.Entry(parent, textvariable=var)
            w.grid(row=row, column=1, sticky="ew" if f.kind != "choice" else "w")
            self.entries[f.key] = w
            if f.kind == "path":
                ttk.Button(parent, text="Chọn…", command=lambda var=var: self._pick_file(var)).grid(row=row, column=2, padx=(6, 0))
        self.vars[f.key] = var
        row += 1
        if f.help:
            ttk.Label(parent, text=f.help, style="Hint.TLabel", wraplength=560).grid(
                row=row, column=1 if f.kind != "bool" else 0, columnspan=2, sticky="w", pady=(0, 2))
            row += 1
        return row

    def _pick_file(self, var):
        p = filedialog.askopenfilename(parent=self.win, filetypes=[("GGUF model", "*.gguf"), ("All", "*.*")])
        if p:
            var.set(p)

    def _model_extras(self, parent, row):
        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        self.conn = tk.StringVar()
        btn = ttk.Button(parent, text="Tải danh sách model từ Ollama", command=self._load_models)
        btn.grid(row=row + 1, column=0, columnspan=2, sticky="w")
        ttk.Label(parent, textvariable=self.conn, style="Hint.TLabel", wraplength=560).grid(
            row=row + 2, column=0, columnspan=3, sticky="w", pady=4)
        return row + 3

    def _load_models(self):
        host = self.vars["host"].get().rstrip("/")
        models = list_models(host)
        if not models:
            self.conn.set(f"Không kết nối được {host}. Ollama đã chạy chưa (`ollama serve`)?")
            return
        self.conn.set(f"{len(models)} model: " + ", ".join(models))
        self._popup_models(models)

    def _popup_models(self, models):
        top = tk.Toplevel(self.win)
        top.title("Chọn model")
        top.transient(self.win)
        lb = tk.Listbox(top, height=min(len(models), 12), activestyle="none")
        for m in models:
            lb.insert("end", m)
        lb.pack(fill="both", expand=True, padx=10, pady=10)

        def pick(_=None):
            if lb.curselection():
                self.vars["ollama_model"].set(models[lb.curselection()[0]])
                top.destroy()

        lb.bind("<Double-Button-1>", pick)
        ttk.Button(top, text="Chọn", command=pick).pack(pady=(0, 10))

    def _dictionary_extras(self, parent, row):
        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        d = self.cfg.dictionary
        info = f"{len(d)} từ trong {len(d.entries)} nhóm — {self.cfg.dict_files[0]}" if self.cfg.dict_files else ""
        ttk.Label(parent, text=info, style="Hint.TLabel", wraplength=560).grid(row=row + 1, column=0, columnspan=3, sticky="w")
        ttk.Button(parent, text="Mở trình sửa từ điển…", command=self.app.open_dictionary).grid(
            row=row + 2, column=0, columnspan=2, sticky="w", pady=6)

    def _build_prompt_tab(self):
        outer = ttk.Frame(self.nb, padding=(16, 10))
        self.nb.add(outer, text=PROMPT_TAB)
        outer.columnconfigure(0, weight=1)
        self.prompt_boxes = {}
        specs = [
            ("system", "System prompt (chỉ dẫn dịch)", self.cfg.system_prompt, self.cfg.system_file),
            ("user", "Mẫu tin nhắn người dùng — dùng {text} cho đoạn cần dịch", self.cfg.user_template, self.cfg.user_file),
            ("manual", "Chỉ dẫn gửi kèm đầu mỗi khối khi dịch thủ công qua chat", self.cfg.manual_instruction, self.cfg.manual_file),
        ]
        for i, (key, title, text, path) in enumerate(specs):
            ttk.Label(outer, text=title, style="Heading.TLabel").grid(row=3 * i, column=0, sticky="w", pady=(8 if i else 0, 2))
            box = scrolledtext.ScrolledText(outer, height=8 if key == "system" else 4, wrap="word", font=("Consolas", 10))
            box.insert("1.0", text)
            box.grid(row=3 * i + 1, column=0, sticky="nsew")
            outer.rowconfigure(3 * i + 1, weight=3 if key == "system" else 1)
            hint = f"File: {path}" if path else "Không có file khai báo — thay đổi chỉ áp dụng cho phiên này."
            ttk.Label(outer, text=hint, style="Hint.TLabel").grid(row=3 * i + 2, column=0, sticky="w")
            self.prompt_boxes[key] = (box, path, text)
        return outer

    # ---- hành động
    def collect(self):
        values = {}
        for f in sm.FIELDS:
            var = self.vars[f.key]
            values[f.key] = bool(var.get()) if f.kind == "bool" else sm.parse_value(f, var.get())
        return values

    def reset(self):
        for f in sm.FIELDS:
            if f.key in ("model_path",):
                continue
            d = sm.defaults()[f.key]
            if f.kind == "bool":
                self.vars[f.key].set(bool(d))
            else:
                self.vars[f.key].set(sm.to_text(f, d))
        for key, text in (("system", cfgmod.DEFAULT_SYSTEM_PROMPT), ("user", cfgmod.DEFAULT_USER_TEMPLATE),
                          ("manual", cfgmod.DEFAULT_MANUAL_INSTRUCTION)):
            box = self.prompt_boxes[key][0]
            box.delete("1.0", "end")
            box.insert("1.0", text)
        self.msg.set("Đã đưa về giá trị mặc định (chưa lưu). Bấm Áp dụng hoặc Lưu để dùng.")

    def commit(self, persist):
        try:
            values = self.collect()
        except ValueError as e:
            self.msg.set(str(e))
            return
        prompts = {k: box.get("1.0", "end-1c").strip() for k, (box, _, _) in self.prompt_boxes.items()}
        if not prompts["system"]:
            self.msg.set("System prompt không được để trống.")
            return
        try:
            sm.apply_values(self.cfg, values)
        except Exception as e:  # noqa: BLE001
            self.msg.set(f"Giá trị không dùng được: {e}")
            return
        self.cfg.system_prompt = prompts["system"]
        self.cfg.user_template = prompts["user"] or cfgmod.DEFAULT_USER_TEMPLATE
        self.cfg.manual_instruction = prompts["manual"] or cfgmod.DEFAULT_MANUAL_INSTRUCTION
        saved = ""
        if persist:
            try:
                updates = sm.overrides(self.initial, values)
                if updates:
                    cfgmod.save_overrides(updates, self.cfg.local_config_path)
                    saved = f"Đã lưu vào {self.cfg.local_config_path}. "
                changed = []
                for key, (box, path, original) in self.prompt_boxes.items():
                    if path and prompts[key] != original.strip():
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(prompts[key] + "\n", encoding="utf-8")
                        changed.append(path.name)
                if changed:
                    saved += "Đã ghi " + ", ".join(changed) + "."
            except OSError as e:
                messagebox.showerror("Lỗi khi lưu", str(e), parent=self.win)
                return
        self.app.on_settings_changed(saved or "Đã áp dụng cho phiên này.")
        self.win.destroy()
