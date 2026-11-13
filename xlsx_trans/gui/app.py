"""Cửa sổ chính: chọn nguồn, vài tùy chọn nhanh, tiến độ và nhật ký. Mọi tùy chọn còn lại nằm trong Cài đặt."""
import copy
import importlib.util
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import __version__, batch, manual, pipeline
from ..ollama import list_models
from . import theme
from .bus import UiBus
from .dict_dialog import DictionaryDialog, ReviewDialog
from .manual_dialog import ManualDialog
from .settings_dialog import SettingsDialog
from .state import UiState
from .util import estimate_eta, format_duration, open_path
from .widgets import Card, LogView, Stat


class Callbacks:
    """Cầu nối cho luồng dịch: mọi cập nhật đi qua hàng đợi, riêng review chờ người dùng trả lời trên luồng giao diện."""

    def __init__(self, app):
        self.app = app

    def log(self, msg):
        self.app.bus.put("log", msg)

    def progress(self, done, total):
        self.app.bus.put("unit", done, total)

    def file_progress(self, done, total, rel):
        self.app.bus.put("file", done, total, str(rel))

    def should_stop(self):
        return self.app.stop_flag

    def review(self, cands):
        return self.app.bus.call(lambda: ReviewDialog(self.app, cands).run())


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = UiState()
        self.stop_flag = False
        self.running = False
        self.out_path = None
        self.plan_token = 0
        self.t0 = 0.0
        self.counts = {"error": 0, "warn": 0}
        self.files = (0, 1)
        self.unit_fraction = 0.0

        self.root = root = tk.Tk()
        root.title("Excel JP → EN")
        root.geometry(self.state["geometry"] or "1000x900")
        root.minsize(860, 760)
        self.theme_name = self.state["theme"] if self.state["theme"] in theme.PALETTES else "light"
        self.pal = theme.apply(root, self.theme_name)
        self.bus = UiBus(root, self.on_event)
        self.cb = Callbacks(self)
        root.report_callback_exception = self._tk_error

        self.path_var = tk.StringVar()
        self.mode_var = tk.StringVar(value=cfg.mode)
        self.md_var = tk.BooleanVar(value=cfg.md)
        self.suggest_var = tk.BooleanVar(value=cfg.suggest)
        self.engine_var = tk.StringVar()
        self.engine_status = tk.StringVar(value="Đang kiểm tra…")
        self.plan_files = tk.StringVar()
        self.plan_out = tk.StringVar()
        self.task_var = tk.StringVar(value="Sẵn sàng")
        self.total_text = tk.StringVar(value="")
        self.file_text = tk.StringVar(value="")
        self.summary_var = tk.StringVar()
        self.status_var = tk.StringVar()

        self._build()
        self._bind()
        self.update_engine_label()
        self.check_engine()
        for w in cfg.warnings:
            self.log_view.add(f"Cảnh báo: {w}")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(500, self._tick)

    # ---------------------------------------------------------------- dựng giao diện
    def _build(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        head = ttk.Frame(root, padding=(20, 16, 20, 4))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Excel JP → EN", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(head, text="Dịch Excel bằng model chạy trên máy bạn — giữ nguyên shape, biểu đồ, định dạng.",
                  style="Sub.TLabel").grid(row=1, column=0, sticky="w")
        self.theme_btn = ttk.Button(head, width=3, command=self.toggle_theme)
        self.theme_btn.grid(row=0, column=1, rowspan=2, padx=(0, 6))
        ttk.Button(head, text="⚙  Cài đặt", command=lambda: self.open_settings()).grid(row=0, column=2, rowspan=2)
        self._sync_theme_btn()

        body = ttk.Frame(root, padding=(20, 8, 20, 6))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(4, weight=1)

        # 1. Nguồn
        src = Card(body, "1  Chọn file hoặc folder")
        src.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        b = src.body
        b.columnconfigure(0, weight=1)
        self.path_entry = ttk.Entry(b, textvariable=self.path_var, font=("Segoe UI", 11))
        self.path_entry.grid(row=0, column=0, sticky="ew", ipady=4)
        ttk.Button(b, text="File…", command=self.browse_file).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(b, text="Folder…", command=self.browse_dir).grid(row=0, column=2, padx=(6, 0))
        ttk.Label(b, textvariable=self.plan_files, style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(b, textvariable=self.plan_out, style="Hint.TLabel").grid(row=2, column=0, columnspan=3, sticky="w")

        # 2. Tùy chọn nhanh
        opt = Card(body, "2  Tùy chọn nhanh")
        opt.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        o = opt.body
        o.columnconfigure(4, weight=1)
        ttk.Radiobutton(o, text="Thay bằng bản dịch", value="replace", variable=self.mode_var, style="Toolbutton").grid(row=0, column=0)
        ttk.Radiobutton(o, text="Song ngữ (JP + EN)", value="bilingual", variable=self.mode_var, style="Toolbutton").grid(row=0, column=1, padx=(6, 18))
        ttk.Checkbutton(o, text="Xuất thêm Markdown", variable=self.md_var).grid(row=0, column=2, padx=(0, 14))
        ttk.Checkbutton(o, text="Gợi ý từ điển", variable=self.suggest_var).grid(row=0, column=3)
        eng = ttk.Frame(o)
        eng.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(12, 0))
        eng.columnconfigure(1, weight=1)
        ttk.Label(eng, text="Model", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(eng, textvariable=self.engine_var, font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.engine_dot = ttk.Label(eng, textvariable=self.engine_status, style="Muted.TLabel")
        self.engine_dot.grid(row=0, column=2, padx=10)
        ttk.Button(eng, text="Đổi model…", command=lambda: self.open_settings("Mô hình")).grid(row=0, column=3)

        # 3. Hành động
        act = ttk.Frame(body)
        act.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        act.columnconfigure(3, weight=1)
        self.start_btn = ttk.Button(act, text="▶  Bắt đầu dịch", style="Big.Accent.TButton", command=self.start)
        self.start_btn.grid(row=0, column=0)
        self.manual_btn = ttk.Button(act, text="Dịch thủ công (chat)…", command=self.open_manual)
        self.manual_btn.grid(row=0, column=1, padx=(10, 0))
        ttk.Button(act, text="Từ điển…", command=self.open_dictionary).grid(row=0, column=2, padx=(10, 0))
        self.stop_btn = ttk.Button(act, text="■  Dừng", state="disabled", command=self.stop)
        self.stop_btn.grid(row=0, column=4)

        # 4. Tiến độ
        prog = Card(body, "3  Tiến độ")
        prog.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        p = prog.body
        p.columnconfigure(1, weight=1)
        ttk.Label(p, textvariable=self.task_var).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(p, text="Tổng", style="Muted.TLabel", width=8).grid(row=1, column=0, sticky="w")
        self.pbar_total = ttk.Progressbar(p, mode="determinate")
        self.pbar_total.grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(p, textvariable=self.total_text, style="Muted.TLabel", width=14, anchor="e").grid(row=1, column=2)
        ttk.Label(p, text="File này", style="Muted.TLabel", width=8).grid(row=2, column=0, sticky="w")
        self.pbar_file = ttk.Progressbar(p, mode="determinate")
        self.pbar_file.grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(p, textvariable=self.file_text, style="Muted.TLabel", width=14, anchor="e").grid(row=2, column=2)
        stats = ttk.Frame(p)
        stats.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.stat_time, self.stat_eta, self.stat_err, self.stat_warn = (
            Stat(stats, "Thời gian"), Stat(stats, "Còn lại (ước tính)"), Stat(stats, "Lỗi"), Stat(stats, "Cảnh báo"))
        for i, s in enumerate((self.stat_time, self.stat_eta, self.stat_err, self.stat_warn)):
            s.grid(row=0, column=i, sticky="w", padx=(0, 36))
        sumrow = ttk.Frame(p)
        sumrow.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        sumrow.columnconfigure(0, weight=1)
        self.summary_lbl = ttk.Label(sumrow, textvariable=self.summary_var)
        self.summary_lbl.grid(row=0, column=0, sticky="w")
        self.open_btn = ttk.Button(sumrow, text="Mở thư mục kết quả", command=self.open_output)
        self.open_btn.grid(row=0, column=1)
        self.open_btn.grid_remove()
        self._reset_stats()

        # 5. Nhật ký
        logc = Card(body, "Nhật ký")
        logc.grid(row=4, column=0, sticky="nsew")
        lb = logc.body
        lb.columnconfigure(0, weight=1)
        lb.rowconfigure(1, weight=1)
        tools = ttk.Frame(lb)
        tools.grid(row=0, column=0, sticky="e", pady=(0, 6))
        ttk.Button(tools, text="Copy", command=self.copy_log).pack(side="left")
        ttk.Button(tools, text="Xóa", command=lambda: self.log_view.clear()).pack(side="left", padx=(6, 0))
        self.log_view = LogView(lb, self.pal)
        self.log_view.grid(row=1, column=0, sticky="nsew")

        status = ttk.Frame(root, padding=(20, 2, 20, 8))
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var, style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(status, text=f"v{__version__}", style="Hint.TLabel").grid(row=0, column=1)

    def _bind(self):
        self.path_var.trace_add("write", lambda *_: self.refresh_plan())
        self.mode_var.trace_add("write", lambda *_: self._set("mode", self.mode_var.get()))
        self.md_var.trace_add("write", lambda *_: (self._set("md", self.md_var.get()), self.refresh_plan()))
        self.suggest_var.trace_add("write", lambda *_: self._set("suggest", self.suggest_var.get()))
        r = self.root
        r.bind("<Control-o>", lambda e: self.browse_file())
        r.bind("<Control-O>", lambda e: self.browse_dir())
        r.bind("<Control-comma>", lambda e: self.open_settings())
        r.bind("<Control-Return>", lambda e: self.start())
        r.bind("<Escape>", lambda e: self.stop() if self.running else None)

    def _set(self, name, value):
        setattr(self.cfg, name, value)

    # ---------------------------------------------------------------- nguồn và kế hoạch
    def browse_file(self):
        p = filedialog.askopenfilename(initialdir=self.state["last_dir"] or None,
                                       filetypes=[("Excel", "*.xlsx *.xlsm"), ("All", "*.*")])
        if p:
            self.path_var.set(p)
            self.state["last_dir"] = str(Path(p).parent)

    def browse_dir(self):
        p = filedialog.askdirectory(initialdir=self.state["last_dir"] or None)
        if p:
            self.path_var.set(p)
            self.state["last_dir"] = str(Path(p).parent)

    def refresh_plan(self):
        """Tính kế hoạch (số file, tên output) ở luồng nền để không đơ khi folder lớn / ổ mạng."""
        self.plan_token += 1
        token = self.plan_token
        text = self.path_var.get().strip().strip('"')
        cfg = copy.copy(self.cfg)
        if not text:
            self.plan_files.set("")
            self.plan_out.set("")
            return

        def work():
            p = Path(text).expanduser()
            if not p.exists():
                self.bus.put("plan", token, "Không tìm thấy đường dẫn này.", "")
                return
            try:
                if p.is_dir():
                    plan = batch.plan_folder(p, cfg)
                    parts = [f"{len(plan.jobs)} file Excel"]
                    if plan.unsupported:
                        parts.append(f"{len(plan.unsupported)} file .xls/.xlsb bị bỏ qua")
                    out = f"→ {plan.out_dir.name}/" + (f"   và   {plan.md_dir.name}/" if plan.md_dir else "") + "   (cạnh folder đã chọn)"
                    self.bus.put("plan", token, " · ".join(parts), out)
                else:
                    out = Path(pipeline.default_out(p, cfg)).name
                    self.bus.put("plan", token, p.name, f"→ {out}" + (f"   và   {Path(out).with_suffix('.md').name}" if cfg.md else ""))
            except (ValueError, OSError) as e:
                self.bus.put("plan", token, str(e), "")

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- model / engine
    def update_engine_label(self):
        c = self.cfg
        if c.backend == "llama_cpp":
            self.engine_var.set(f"llama.cpp · {Path(str(c.model_path)).name}")
        else:
            self.engine_var.set(f"Ollama · {c.ollama_model}")

    def check_engine(self):
        c = copy.copy(self.cfg)
        self.engine_status.set("Đang kiểm tra…")
        self.engine_dot.configure(style="Muted.TLabel")

        def work():
            if c.backend == "llama_cpp":
                if not Path(str(c.model_path)).is_file():
                    self.bus.put("engine", "err", "● Không thấy file .gguf")
                elif importlib.util.find_spec("llama_cpp") is None:
                    self.bus.put("engine", "err", "● Thiếu llama-cpp-python")
                else:
                    self.bus.put("engine", "ok", "● Sẵn sàng")
                return
            models = list_models(c.host)
            if not models:
                self.bus.put("engine", "err", "● Không kết nối được Ollama")
            elif c.ollama_model not in models and f"{c.ollama_model}:latest" not in models:
                self.bus.put("engine", "warn", f"● Chưa có model — ollama pull {c.ollama_model}")
            else:
                self.bus.put("engine", "ok", f"● Kết nối được · {len(models)} model")

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- dialogs
    def open_settings(self, tab=None):
        if self.running:
            messagebox.showinfo("Đang chạy", "Hãy chờ hoặc dừng lượt dịch hiện tại trước khi đổi cài đặt.")
            return
        SettingsDialog(self, tab)

    def open_dictionary(self):
        if not self.cfg.dict_files:
            messagebox.showinfo("Từ điển", "Chưa khai báo file từ điển trong config (dictionary.files).")
            return
        DictionaryDialog(self)

    def on_settings_changed(self, message=""):
        """Gọi sau khi Cài đặt / Từ điển lưu: đồng bộ các điều khiển ở màn hình chính."""
        c = self.cfg
        self.mode_var.set(c.mode)
        self.md_var.set(c.md)
        self.suggest_var.set(c.suggest)
        self.update_engine_label()
        self.check_engine()
        self.refresh_plan()
        if message:
            self.status_var.set(message)
            self.log_view.add(message)

    # ---------------------------------------------------------------- chạy
    def _validate_source(self):
        text = self.path_var.get().strip().strip('"')
        if not text or not Path(text).expanduser().exists():
            messagebox.showerror("Thiếu nguồn", "Hãy chọn một file Excel hoặc một folder trước.")
            return None
        return Path(text).expanduser()

    def start(self):
        if self.running:
            return
        src = self._validate_source()
        if src is None:
            return
        if self.engine_status.get().startswith("● Không") and not messagebox.askyesno(
                "Model chưa sẵn sàng", f"{self.engine_status.get()[2:]}.\nVẫn thử chạy?"):
            return
        cfg = copy.copy(self.cfg)
        self.run_job(f"Đang dịch: {src.name}", lambda cb: self._translate(src, cfg, cb))

    def _translate(self, src, cfg, cb):
        if src.is_dir():
            res = batch.process_folder(src, cfg, log=cb.log, progress=cb.progress, file_progress=cb.file_progress,
                                       should_stop=cb.should_stop, review=cb.review)
            return self._folder_summary(res)
        out = pipeline.default_out(src, cfg)
        applied, errors = pipeline.process_xlsx(src, out, cfg, log=cb.log, progress=cb.progress,
                                                should_stop=cb.should_stop, review=cb.review)
        return {"title": f"{src.name}: dịch {applied} đoạn", "errors": errors, "failed": 0,
                "stopped": cb.should_stop(), "out": Path(out)}

    @staticmethod
    def _folder_summary(res):
        return {"title": f"{len(res.ok)} file xong", "errors": res.errors, "failed": len(res.failed),
                "stopped": res.stopped, "interrupted": len(res.interrupted),
                "out": res.plan.out_dir if res.plan else None}

    def finish_manual(self, session, cb):
        res = session.finish(log=cb.log, progress=cb.progress, file_progress=cb.file_progress, should_stop=cb.should_stop)
        if session.is_folder:
            return self._folder_summary(res)
        applied, errors = res
        out = session.out_dir or pipeline.default_out(session.input, session.cfg)
        return {"title": f"{session.input.name}: dịch {applied} đoạn", "errors": errors, "failed": 0,
                "stopped": cb.should_stop(), "out": Path(out)}

    def run_job(self, title, fn):
        """Chạy fn(callbacks) ở luồng nền; kết quả (dict tóm tắt) quay về qua sự kiện 'done'."""
        self.running, self.stop_flag = True, False
        self.out_path = None
        self.t0 = time.time()
        self.counts = {"error": 0, "warn": 0}
        self.files, self.unit_fraction = (0, 1), 0.0
        self.task_var.set(title)
        self._reset_stats()
        self.summary_var.set("")
        self.open_btn.grid_remove()
        for b in (self.start_btn, self.manual_btn):
            b.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.pbar_total.configure(value=0, maximum=1)
        self.pbar_file.configure(value=0, maximum=1)

        def work():
            try:
                self.bus.put("done", fn(self.cb), None)
            except Exception as e:  # noqa: BLE001
                self.bus.put("done", None, e)

        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        if self.running:
            self.stop_flag = True
            self.task_var.set("Đang dừng sau đoạn hiện tại…")
            self.stop_btn.configure(state="disabled")

    def open_manual(self):
        src = self._validate_source()
        if src is None or self.running:
            return
        self.manual_btn.configure(state="disabled")
        self.task_var.set("Dịch thủ công: đang quét và chia khối…")
        cfg = copy.copy(self.cfg)

        def work():
            try:
                session = manual.ManualSession(cfg, src)
                session.scan()
                self.bus.put("manual_ready", session, None)
            except Exception as e:  # noqa: BLE001
                self.bus.put("manual_ready", None, e)

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- sự kiện từ luồng nền
    def on_event(self, kind, *a):
        if kind == "log":
            level = self.log_view.add(a[0])
            if level in ("error", "warn"):
                self.counts[level] += 1
        elif kind == "unit":
            done, total = a
            self.pbar_file.configure(maximum=max(total, 1), value=done)
            self.unit_fraction = done / total if total else 1.0
            self.file_text.set(f"{int(self.unit_fraction * 100)}%")
            if self.files[1] == 1:  # một file: thanh tổng chạy theo thanh file
                self.pbar_total.configure(maximum=max(total, 1), value=done)
                self.total_text.set(self.file_text.get())
        elif kind == "file":
            done, total, rel = a
            self.files = (done, total)
            self.pbar_total.configure(maximum=max(total, 1), value=done)
            self.total_text.set(f"{done}/{total} file")
            if done < total:
                self.task_var.set(f"Đang dịch: {rel}")
        elif kind == "plan":
            token, files, out = a
            if token == self.plan_token:
                self.plan_files.set(files)
                self.plan_out.set(out)
        elif kind == "engine":
            level, text = a
            self.engine_status.set(text)
            self.engine_dot.configure(style={"ok": "Ok.TLabel", "warn": "Warn.TLabel", "err": "Err.TLabel"}[level])
        elif kind == "manual_ready":
            session, err = a
            self.manual_btn.configure(state="normal" if not self.running else "disabled")
            self.task_var.set("Sẵn sàng")
            if err:
                self.log_view.add(f"LỖI: {err}")
                messagebox.showerror("Dịch thủ công", str(err))
            else:
                if not session.blocks:
                    self.log_view.add("Mọi chuỗi đã có bản dịch trong cache (hoặc không có gì cần dịch). Bấm Tạo file để xuất kết quả.")
                ManualDialog(self, session)
        elif kind == "done":
            self._finish_run(*a)

    def _finish_run(self, summary, err):
        self.running = False
        self.cfg.reload_dictionary()  # gợi ý có thể vừa thêm từ vào file từ điển
        self.start_btn.configure(state="normal")
        self.manual_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        elapsed = format_duration(time.time() - self.t0)
        if err is not None:
            self.log_view.add(f"LỖI: {err}")
            self.task_var.set("Dừng do lỗi")
            self._summary("err", f"✖  Lỗi: {err}")
            return
        self.pbar_file.configure(value=self.pbar_file["maximum"])
        failed = summary.get("failed", 0)
        errors = summary.get("errors", 0)
        extra = ""
        if failed:
            extra += f" · {failed} file lỗi"
        if errors:
            extra += f" · {errors} đoạn lỗi"
        if summary.get("stopped"):
            self._summary("warn", f"⏸  Đã dừng — {summary['title']}{extra} · {elapsed}")
            self.task_var.set("Đã dừng (tiến độ đã lưu trong cache, chạy lại sẽ tiếp tục)")
        elif failed or errors:
            self._summary("warn", f"✔  Hoàn tất có cảnh báo — {summary['title']}{extra} · {elapsed}")
            self.task_var.set("Hoàn tất")
        else:
            self._summary("ok", f"✔  Hoàn tất — {summary['title']} · {elapsed}")
            self.task_var.set("Hoàn tất")
        self.out_path = summary.get("out")
        if self.out_path and Path(self.out_path).exists():
            self.open_btn.grid()
        self.stat_eta.set("—")

    def _summary(self, level, text):
        self.summary_var.set(text)
        self.summary_lbl.configure(style={"ok": "Ok.TLabel", "warn": "Warn.TLabel", "err": "Err.TLabel"}[level])

    def _reset_stats(self):
        self.stat_time.set("00:00")
        self.stat_eta.set("—")
        self.stat_err.set("0")
        self.stat_warn.set("0")
        self.total_text.set("")
        self.file_text.set("")

    def _tick(self):
        if self.running:
            elapsed = time.time() - self.t0
            self.stat_time.set(format_duration(elapsed))
            eta = estimate_eta(elapsed, self.files[0], self.files[1], self.unit_fraction)
            self.stat_eta.set(format_duration(eta) if eta is not None else "…")
            self.stat_err.set(str(self.counts["error"]), "Err.TLabel" if self.counts["error"] else None)
            self.stat_warn.set(str(self.counts["warn"]), "Warn.TLabel" if self.counts["warn"] else None)
        self.root.after(500, self._tick)

    # ---------------------------------------------------------------- tiện ích
    def open_output(self):
        if self.out_path:
            target = Path(self.out_path)
            open_path(target if target.is_dir() else target.parent)

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_view.contents())
        self.status_var.set("Đã copy nhật ký vào clipboard.")

    def toggle_theme(self):
        self.theme_name = "dark" if self.theme_name == "light" else "light"
        self.pal = theme.apply(self.root, self.theme_name)
        self.log_view.restyle(self.pal)
        self.state["theme"] = self.theme_name
        self._sync_theme_btn()
        self.check_engine_style()

    def check_engine_style(self):
        """Màu chữ trạng thái giữ theo mức hiện tại sau khi đổi theme."""
        text = self.engine_status.get()
        style = "Err.TLabel" if text.startswith("● Không") or "Thiếu" in text else "Warn.TLabel" if "Chưa có" in text else \
            "Ok.TLabel" if text.startswith("● ") else "Muted.TLabel"
        self.engine_dot.configure(style=style)

    def _sync_theme_btn(self):
        self.theme_btn.configure(text="☀" if self.theme_name == "dark" else "☾")

    def _tk_error(self, exc, val, tb):
        self.log_view.add(f"LỖI giao diện: {val}")

    def on_close(self):
        if self.running and not messagebox.askyesno("Đang dịch", "Đang dịch dở. Dừng và thoát?\n(Tiến độ đã dịch được lưu trong cache.)"):
            return
        self.stop_flag = True
        self.state["geometry"] = self.root.geometry()
        self.state.save()
        self.bus.close()
        self.root.destroy()

    def mainloop(self):
        self.root.mainloop()


def run(cfg):
    App(cfg).mainloop()
