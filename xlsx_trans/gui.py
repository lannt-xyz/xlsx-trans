"""Giao diện tkinter: chọn một file hoặc cả folder, chọn model, kiểu ghi, theo dõi tiến độ."""
import copy
import threading
from pathlib import Path

from . import batch, manual, pipeline
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

    def edit_dictionary():
        target = cfg.dict_files[0]
        win = tk.Toplevel(root)
        win.title(f"Từ điển giữ nguyên tiếng Nhật — {target.name}")
        win.geometry("520x460")
        ttk.Label(
            win, text="Mỗi dòng một từ; [nhóm] để chia nhóm; # là ghi chú. Các từ này sẽ KHÔNG bị dịch.",
            wraplength=480,
        ).pack(anchor="w", padx=8, pady=6)
        box = scrolledtext.ScrolledText(win)
        box.pack(fill="both", expand=True, padx=8)
        try:
            box.insert("1.0", target.read_text(encoding="utf-8-sig"))
        except OSError:
            pass

        def save():
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(box.get("1.0", "end-1c").rstrip() + "\n", encoding="utf-8")
            except OSError as e:
                messagebox.showerror("Lỗi", str(e), parent=win)
                return
            cfg.reload_dictionary()
            win.destroy()

        ttk.Button(win, text="Lưu", command=save).pack(pady=8)

    ttk.Button(frm, text="Từ điển…", command=edit_dictionary).grid(row=11, column=2, padx=4, pady=4, sticky="e")

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
    manual_btn = ttk.Button(btns, text="Dịch thủ công (chat)…", command=lambda: manual_dialog())
    start_btn.pack(side="left", padx=4)
    manual_btn.pack(side="left", padx=4)
    stop_btn.pack(side="left", padx=4)

    def gui_review(cands):
        """Chạy ở luồng dịch: mở hộp thoại trên luồng giao diện rồi chờ người dùng quyết định."""
        done = threading.Event()
        result = {}

        def show():
            win = tk.Toplevel(root)
            win.title("Gợi ý thêm vào từ điển (giữ nguyên tiếng Nhật)")
            win.geometry("640x460")
            win.transient(root)
            ttk.Label(
                win, wraplength=600,
                text="Các từ dưới đây có vẻ là danh từ riêng (tên người, màn hình, nút, message...) và chưa có trong từ điển. "
                "Chọn những từ cần GIỮ NGUYÊN tiếng Nhật.",
            ).pack(anchor="w", padx=8, pady=6)
            lb = tk.Listbox(win, selectmode="extended", activestyle="none")
            lb.pack(fill="both", expand=True, padx=8)
            for c in cands:
                lb.insert("end", f"{c.term}   [{c.category}] ×{c.count}   «{c.example}»")

            def finish(mode):
                chosen = set(lb.curselection())
                for i, c in enumerate(cands):
                    if i in chosen:
                        result[c.term] = "add"
                    elif mode == "never":
                        result[c.term] = "ignore"
                win.destroy()
                done.set()

            bar = ttk.Frame(win)
            bar.pack(pady=8)
            ttk.Button(bar, text="Thêm các từ đã chọn", command=lambda: finish("add")).pack(side="left", padx=4)
            ttk.Button(bar, text="Thêm đã chọn, không hỏi lại các từ còn lại", command=lambda: finish("never")).pack(side="left", padx=4)
            ttk.Button(bar, text="Bỏ qua lần này", command=lambda: (result.clear(), win.destroy(), done.set())).pack(side="left", padx=4)
            win.protocol("WM_DELETE_WINDOW", lambda: (result.clear(), win.destroy(), done.set()))

        root.after(0, show)
        done.wait()
        return result

    def manual_dialog():
        """Dịch qua chat bên ngoài: copy từng khối, dán kết quả lại, rồi tạo file."""
        src = path_var.get()
        if not src or not Path(src).exists():
            messagebox.showerror("Lỗi", "Chọn file Excel hoặc folder trước.")
            return
        manual_btn.config(state="disabled")
        log("Dịch thủ công: đang quét và chia khối...")

        def scan():
            try:
                session = manual.ManualSession(current_cfg(), src)
                session.scan()
            except Exception as e:  # noqa: BLE001
                log(f"LỖI: {e}")
                root.after(0, lambda: manual_btn.config(state="normal"))
                return
            root.after(0, lambda: show(session))

        def show(session):
            manual_btn.config(state="normal")
            if not session.blocks:
                log("Mọi chuỗi đã có bản dịch trong cache (hoặc không có gì cần dịch). Bấm Tạo file để xuất kết quả.")
            win = tk.Toplevel(root)
            win.title("Dịch thủ công qua chat")
            win.geometry("760x640")
            pos = {"i": 0}
            head_var = tk.StringVar()
            status_var = tk.StringVar()

            ttk.Label(win, textvariable=head_var, font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
            ttk.Label(win, text="1) Copy khối này vào chat   2) Dán kết quả chat vào ô dưới   3) Lưu kết quả").pack(anchor="w", padx=8)
            prompt_box = scrolledtext.ScrolledText(win, height=12, state="disabled")
            prompt_box.pack(fill="both", expand=True, padx=8, pady=4)
            bar1 = ttk.Frame(win)
            bar1.pack(fill="x", padx=8)
            result_box = scrolledtext.ScrolledText(win, height=12)
            result_box.pack(fill="both", expand=True, padx=8, pady=4)
            ttk.Label(win, textvariable=status_var, wraplength=720, foreground="#555").pack(anchor="w", padx=8)
            bar2 = ttk.Frame(win)
            bar2.pack(pady=8)

            def current():
                return session.blocks[pos["i"]] if session.blocks else None

            def refresh():
                n = len(session.blocks)
                pos["i"] = min(pos["i"], max(n - 1, 0))
                b = current()
                prompt_box.configure(state="normal")
                prompt_box.delete("1.0", "end")
                result_box.delete("1.0", "end")
                if b:
                    head_var.set(
                        f"Khối {pos['i'] + 1}/{n} — {len(b.items)} mục — {b.tokens} token ({session.counter.kind}) — "
                        f"đã có {session.done_count()}/{session.total} bản dịch"
                    )
                    prompt_box.insert("1.0", b.prompt)
                else:
                    head_var.set(f"Hết khối cần dịch — đã có {session.done_count()}/{session.total} bản dịch. Bấm Tạo file.")
                prompt_box.configure(state="disabled")

            def copy_block():
                b = current()
                if b:
                    win.clipboard_clear()
                    win.clipboard_append(b.prompt)
                    status_var.set("Đã copy khối vào clipboard. Dán vào chat rồi chờ kết quả.")

            def save_result():
                b = current()
                if not b:
                    return
                text = result_box.get("1.0", "end-1c")
                if not text.strip():
                    status_var.set("Ô kết quả đang trống.")
                    return
                res = session.apply_output(b, text)
                msg = f"Đã lưu {len(res.saved)} bản dịch."
                if res.suspect:
                    msg += f" {len(res.suspect)} mục vẫn còn tiếng Nhật (chat có thể chưa dịch): {res.suspect}."
                if res.extra:
                    msg += f" Bỏ qua {res.extra} dòng có số không thuộc khối này."
                retry = session.retry_block(b, res) if res.retry_ids else []
                if res.missing:
                    msg += f" Thiếu mục {res.missing}."
                if res.bad:
                    msg += " Lỗi: " + "; ".join(f"{i} ({why})" for i, why in res.bad) + "."
                i = pos["i"]
                session.blocks[i:i + 1] = retry  # khối xong thì bỏ; còn mục thiếu/hỏng thì thay bằng khối mới chỉ gồm các mục đó
                if retry:
                    msg += " Khối mới chỉ gồm các mục này đã thay vào chỗ khối cũ — copy và hỏi lại chat."
                refresh()
                status_var.set(msg)

            def move(d):
                if session.blocks:
                    pos["i"] = (pos["i"] + d) % len(session.blocks)
                    refresh()

            def finish():
                win.destroy()
                stop_flag["stop"] = False
                start_btn.config(state="disabled")
                stop_btn.config(state="normal")

                def run():
                    try:
                        session.finish(log=log, progress=progress, file_progress=file_progress,
                                       should_stop=lambda: stop_flag["stop"])
                    except Exception as e:  # noqa: BLE001
                        log(f"LỖI: {e}")
                    finally:
                        root.after(0, lambda: (start_btn.config(state="normal"), stop_btn.config(state="disabled")))

                threading.Thread(target=run, daemon=True).start()

            ttk.Button(bar1, text="Copy khối này", command=copy_block).pack(side="left")
            ttk.Button(bar1, text="◀ Trước", command=lambda: move(-1)).pack(side="left", padx=(12, 2))
            ttk.Button(bar1, text="Sau ▶", command=lambda: move(1)).pack(side="left")
            ttk.Button(bar2, text="Lưu kết quả của khối này", command=save_result).pack(side="left", padx=4)
            ttk.Button(bar2, text="Tạo file xlsx / md từ bản dịch đã có", command=finish).pack(side="left", padx=4)
            refresh()

        threading.Thread(target=scan, daemon=True).start()

    def worker(src):
        try:
            c = current_cfg()
            should_stop = lambda: stop_flag["stop"]  # noqa: E731
            p = Path(src)
            if p.is_dir():
                batch.process_folder(
                    p, c, log=log, progress=progress, file_progress=file_progress, should_stop=should_stop,
                    review=gui_review,
                )
            else:
                pipeline.process_xlsx(
                    p, pipeline.default_out(p, c), c, log=log, progress=progress, should_stop=should_stop,
                    review=gui_review,
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
