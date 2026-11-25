"""Theme sáng/tối. Dùng `sv-ttk` (kiểu Windows 11) nếu đã cài, không thì tự tạo style trên theme `clam`."""
from tkinter import ttk

PALETTES = {
    "light": dict(bg="#f6f7f9", fg="#1d2129", muted="#6b7280", card="#ffffff", border="#e3e6ea", accent="#2563eb",
                  accent_fg="#ffffff", ok="#15803d", warn="#b45309", err="#b91c1c", log_bg="#ffffff", sel="#dbeafe"),
    "dark": dict(bg="#1b1d22", fg="#eceef2", muted="#9aa3b2", card="#262930", border="#363a43", accent="#4f8ff7",
                 accent_fg="#ffffff", ok="#4ade80", warn="#fbbf24", err="#f87171", log_bg="#1f2228", sel="#31456e"),
}
FONT = ("Segoe UI", 10)
try:  # kiểm tra có sv_ttk không (import thật làm trong apply)
    import sv_ttk as _sv
except ImportError:
    _sv = None


def has_sv():
    return _sv is not None


def apply(root, name):
    """Áp theme `light`/`dark` cho cả cây widget; trả về bảng màu để tô các widget tk thuần (Text, Listbox...)."""
    pal = PALETTES[name]
    style = ttk.Style(root)
    if _sv is not None:
        _sv.set_theme(name)
    else:
        _fallback(style, pal)
    style.configure("Title.TLabel", font=(FONT[0], 17, "bold"))
    style.configure("Sub.TLabel", foreground=pal["muted"])
    style.configure("Muted.TLabel", foreground=pal["muted"])
    style.configure("Hint.TLabel", foreground=pal["muted"], font=(FONT[0], 9))
    style.configure("Heading.TLabel", font=(FONT[0], 11, "bold"))
    style.configure("Ok.TLabel", foreground=pal["ok"])
    style.configure("Warn.TLabel", foreground=pal["warn"])
    style.configure("Err.TLabel", foreground=pal["err"])
    style.configure("Big.Accent.TButton", font=(FONT[0], 11, "bold"), padding=(18, 8))
    root.configure(background=style.lookup("TFrame", "background") or pal["bg"])
    return pal


def _fallback(style, pal):
    style.theme_use("clam")
    bg, fg = pal["bg"], pal["fg"]
    root_opts = dict(background=bg, foreground=fg, fieldbackground=pal["card"], bordercolor=pal["border"],
                     lightcolor=pal["card"], darkcolor=pal["border"], troughcolor=pal["border"], font=FONT)
    style.configure(".", **root_opts)
    style.configure("TFrame", background=bg)
    style.configure("Card.TFrame", background=pal["card"], relief="solid", borderwidth=1, bordercolor=pal["border"])
    style.configure("TLabel", background=bg, foreground=fg)
    style.configure("Card.TLabel", background=pal["card"])
    style.configure("TButton", padding=(12, 6), background=pal["card"], foreground=fg)
    style.map("TButton", background=[("active", pal["sel"]), ("disabled", bg)])
    style.configure("Accent.TButton", background=pal["accent"], foreground=pal["accent_fg"], padding=(14, 6))
    style.map("Accent.TButton", background=[("active", pal["accent"]), ("disabled", pal["border"])],
              foreground=[("disabled", pal["muted"])])
    style.configure("Toolbutton", padding=(12, 5), background=bg)
    style.map("Toolbutton", background=[("selected", pal["accent"]), ("active", pal["sel"])],
              foreground=[("selected", pal["accent_fg"])])
    style.configure("TCheckbutton", background=bg)
    style.configure("TRadiobutton", background=bg)
    style.configure("TNotebook", background=bg)
    style.configure("TProgressbar", background=pal["accent"], troughcolor=pal["border"], thickness=10)
    style.configure("Treeview", background=pal["card"], fieldbackground=pal["card"])
    style.configure("TEntry", padding=5)
    style.configure("TCombobox", padding=4)


def card_style(parent_style="Card.TFrame"):
    return parent_style
