"""Giao diện tkinter. tkinter chỉ được nhập khi mở giao diện, nên CLI / Docker không cần tkinter."""


def run_gui(cfg):
    from .app import run

    return run(cfg)
