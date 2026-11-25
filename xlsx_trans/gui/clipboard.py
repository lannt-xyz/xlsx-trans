"""Clipboard hệ thống. Trên Windows, Tk giữ quyền sở hữu clipboard sau khi app copy và có thể trả về dữ liệu CŨ
(bản app đã copy) dù đã copy nội dung khác từ ứng dụng khác. Vì vậy trên Windows đọc/ghi thẳng bằng Win32 API."""
import sys
import time

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _win_api():
    import ctypes
    from ctypes import wintypes

    u = ctypes.WinDLL("user32", use_last_error=True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    u.OpenClipboard.argtypes, u.OpenClipboard.restype = [wintypes.HWND], wintypes.BOOL
    u.CloseClipboard.argtypes, u.CloseClipboard.restype = [], wintypes.BOOL
    u.EmptyClipboard.argtypes, u.EmptyClipboard.restype = [], wintypes.BOOL
    u.SetClipboardData.argtypes, u.SetClipboardData.restype = [wintypes.UINT, wintypes.HANDLE], wintypes.HANDLE
    u.GetClipboardData.argtypes, u.GetClipboardData.restype = [wintypes.UINT], wintypes.HANDLE
    u.IsClipboardFormatAvailable.argtypes, u.IsClipboardFormatAvailable.restype = [wintypes.UINT], wintypes.BOOL
    k.GlobalAlloc.argtypes, k.GlobalAlloc.restype = [wintypes.UINT, ctypes.c_size_t], wintypes.HGLOBAL
    k.GlobalLock.argtypes, k.GlobalLock.restype = [wintypes.HGLOBAL], wintypes.LPVOID
    k.GlobalUnlock.argtypes, k.GlobalUnlock.restype = [wintypes.HGLOBAL], wintypes.BOOL
    k.GlobalFree.argtypes, k.GlobalFree.restype = [wintypes.HGLOBAL], wintypes.HGLOBAL
    return ctypes, u, k


def _win_open(user32):
    for _ in range(20):  # ứng dụng khác có thể đang giữ clipboard trong chốc lát
        if user32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise OSError("Không mở được clipboard (ứng dụng khác đang giữ).")


def _win_set(text):
    ctypes, u, k = _win_api()
    data = (text.replace("\r\n", "\n").replace("\n", "\r\n") + "\0").encode("utf-16-le")
    _win_open(u)
    try:
        u.EmptyClipboard()
        h = k.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            raise OSError("GlobalAlloc thất bại")
        p = k.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k.GlobalUnlock(h)
        if not u.SetClipboardData(CF_UNICODETEXT, h):
            k.GlobalFree(h)
            raise OSError("SetClipboardData thất bại")
    finally:
        u.CloseClipboard()


def _win_get():
    ctypes, u, k = _win_api()
    _win_open(u)
    try:
        if not u.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        h = u.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = k.GlobalLock(h)
        try:
            return ctypes.wstring_at(p).replace("\r\n", "\n")
        finally:
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()


def set_text(widget, text):
    """Đưa văn bản vào clipboard hệ thống."""
    if sys.platform == "win32":
        try:
            _win_set(text)
            return
        except Exception:  # noqa: BLE001
            pass
    widget.clipboard_clear()
    widget.clipboard_append(text)


def get_text(widget):
    """Đọc văn bản từ clipboard hệ thống; None nếu trống / không phải chữ."""
    if sys.platform == "win32":
        try:
            return _win_get()
        except Exception:  # noqa: BLE001
            pass
    try:
        return widget.clipboard_get()
    except Exception:  # noqa: BLE001  (tk.TclError khi trống)
        return None
