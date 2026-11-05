"""Giao diện tkinter: chọn một file hoặc cả folder, chọn model, kiểu ghi, theo dõi tiến độ."""
import copy
import threading
from pathlib import Path

from . import batch, pipeline
from .ollama import list_models


def run_gui(cfg):
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title("Excel JP → EN (local LLM)")
    root.geometry("700x600")

    path_var = tk.StringVar()
    host_var = tk.StringVar(value=cfg.host)
    model_var = tk.StringVar(value=cfg.ollama_model)
    mode_var = tk.StringVar(value=cfg.mode)
    backend_var = tk.StringVar(value=cfg.backend)
    gguf_var = tk.StringVar(value=str(cfg.model_path))
    md_var = tk.BooleanVar(value=cfg.md)
    info_var = tk.StringVar()
    stop_flag = {"stop": False}

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    def current_cfg():
        """Config + giá trị đang chọn trên giao diện."""
        c = copy.copy(cfg)
        c.host = host_var.get().rstrip("/")
        c.ollama_model = model_var.get()
        c.backend = backend_var.get()
        c.model_path = Path(gguf_var.get()).expanduser()
        c.refresh()
        c.mode = mode_var.get()
        c.md = md_var.get()
        return c

    def show_plan(*_):
        p = Path(path_var.get()) if path_var.get() else None
        if not p or not p.exists():
            info_var.set("")
            return
        c = current_cfg()
        if p.is_dir():
            try:
                out_dir, md_dir = batch.derive_dirs(p.resolve(), c)
                info_var.set("Sẽ tạo: " + out_dir.name + (f"  và  {md_dir.name}" if md_dir else "") + "  (cạnh folder đã chọn)")
            except ValueError as e:
                info_var.set(str(e))
        else:
            info_var.set("Sẽ tạo: " + Path(pipeline.default_out(p, c)).name)

    def browse_file():
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xlsm"), ("All", "*.*")])
        if p:
            path_var.set(p)

    def browse_dir():
        p = filedialog.askdirectory()
        if p:
            path_var.set(p)

    ttk.Label(frm, text="File / folder:").grid(row=0, column=0, sticky="w")
    ttk.Entry(frm, textvariable=path_var).grid(row=0, column=1, sticky="ew")
    bf = ttk.Frame(frm)
    bf.grid(row=0, column=2, padx=4)
    ttk.Button(bf, text="File…", command=browse_file).pack(side="left")
    ttk.Button(bf, text="Folder…", command=browse_dir).pack(side="left", padx=(4, 0))
    ttk.Label(frm, textvariable=info_var, foreground="#555").grid(row=1, column=1, columnspan=2, sticky="w")

    ttk.Label(frm, text="Ollama host:").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=host_var).grid(row=2, column=1, sticky="ew")

    ttk.Label(frm, text="Model:").grid(row=3, column=0, sticky="w")
    model_box = ttk.Combobox(frm, textvariable=model_var, values=[cfg.ollama_model])
    model_box.grid(row=3, column=1, sticky="ew")

    def refresh_models():
        ms = list_models(host_var.get().rstrip("/"))
        if ms:
            model_box["values"] = ms
            if model_var.get() not in ms:
                model_var.set(ms[0])
        else:
            messagebox.showwarning("Ollama", "Không kết nối được Ollama. Đã chạy `ollama serve` chưa?")

    ttk.Button(frm, text="Tải model", command=refresh_models).grid(row=3, column=2, padx=4)

    ttk.Label(frm, text="Backend:").grid(row=9, column=0, sticky="w")
    bk = ttk.Frame(frm)
    bk.grid(row=9, column=1, sticky="w")
    ttk.Radiobutton(bk, text="Ollama", variable=backend_var, value="ollama").pack(side="left")
    ttk.Radiobutton(bk, text="File .gguf (llama.cpp)", variable=backend_var, value="llama_cpp").pack(side="left", padx=10)
    ttk.Label(frm, text="File .gguf:").grid(row=10, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=gguf_var).grid(row=10, column=1, sticky="ew")

    def browse_gguf():
        p = filedialog.askopenfilename(filetypes=[("GGUF model", "*.gguf"), ("All", "*.*")])
        if p:
            gguf_var.set(p)
            backend_var.set("llama_cpp")

    ttk.Button(frm, text="Chọn…", command=browse_gguf).grid(row=10, column=2, padx=4)

    ttk.Label(frm, text="Kiểu ghi:").grid(row=4, column=0, sticky="w", pady=4)
    mf = ttk.Frame(frm)
    mf.grid(row=4, column=1, sticky="w")
    ttk.Radiobutton(mf, text="Thay bằng bản dịch", variable=mode_var, value="replace").pack(side="left")
    ttk.Radiobutton(mf, text="Song ngữ (JP + EN)", variable=mode_var, value="bilingual").pack(side="left", padx=10)
    ttk.Checkbutton(mf, text="Xuất thêm .md", variable=md_var).pack(side="left", padx=10)

    ttk.Label(frm, text="Tổng (file):").grid(row=5, column=0, sticky="w")
    pbar_total = ttk.Progressbar(frm, mode="determinate")
    pbar_total.grid(row=5, column=1, columnspan=2, sticky="ew", pady=(6, 2))
    ttk.Label(frm, text="File hiện tại:").grid(row=6, column=0, sticky="w")
    pbar_file = ttk.Progressbar(frm, mode="determinate")
    pbar_file.grid(row=6, column=1, columnspan=2, sticky="ew", pady=(2, 6))

    logbox = scrolledtext.ScrolledText(frm, height=16, state="disabled")
    logbox.grid(row=7, column=0, columnspan=3, sticky="nsew")
    frm.columnconfigure(1, weight=1)
    frm.rowconfigure(7, weight=1)

    def log(msg):
        def _do():
            logbox.configure(state="normal")
            logbox.insert("end", msg + "\n")
            logbox.see("end")
            logbox.configure(state="disabled")

        root.after(0, _do)

    def progress(done, total):
        def _do():
            pbar_file["maximum"] = max(total, 1)
            pbar_file["value"] = done

        root.after(0, _do)

    def file_progress(done, total, rel):
        def _do():
            pbar_total["maximum"] = max(total, 1)
            pbar_total["value"] = done

        root.after(0, _do)

    btns = ttk.Frame(frm)
    btns.grid(row=8, column=0, columnspan=3, pady=8)
    start_btn = ttk.Button(btns, text="Bắt đầu dịch")
    stop_btn = ttk.Button(btns, text="Dừng", state="disabled")
    start_btn.pack(side="left", padx=4)
    stop_btn.pack(side="left", padx=4)

    def worker(src):
        try:
            c = current_cfg()
            should_stop = lambda: stop_flag["stop"]  # noqa: E731
            p = Path(src)
            if p.is_dir():
                batch.process_folder(
                    p, c, log=log, progress=progress, file_progress=file_progress, should_stop=should_stop
                )
            else:
                pipeline.process_xlsx(
                    p, pipeline.default_out(p, c), c, log=log, progress=progress, should_stop=should_stop
                )
        except Exception as e:  # noqa: BLE001
            log(f"LỖI: {e}")
        finally:
            root.after(0, lambda: (start_btn.config(state="normal"), stop_btn.config(state="disabled")))

    def start():
        src = path_var.get()
        if not src or not Path(src).exists():
            messagebox.showerror("Lỗi", "Chọn file Excel hoặc folder trước.")
            return
        stop_flag["stop"] = False
        pbar_total["value"] = 0
        pbar_file["value"] = 0
        start_btn.config(state="disabled")
        stop_btn.config(state="normal")
        threading.Thread(target=worker, args=(src,), daemon=True).start()

    start_btn.config(command=start)
    stop_btn.config(command=lambda: stop_flag.update(stop=True))
    for v in (path_var, mode_var, md_var):
        v.trace_add("write", show_plan)
    root.after(200, lambda: model_box.__setitem__("values", list_models(cfg.host) or [cfg.ollama_model]))
    root.mainloop()
