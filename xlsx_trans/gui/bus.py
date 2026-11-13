"""Cầu nối luồng: luồng dịch gửi sự kiện vào hàng đợi, luồng giao diện lấy ra theo nhịp (tkinter không an toàn giữa các luồng)."""
import queue
import threading


class UiBus:
    def __init__(self, root, handler, interval_ms=60):
        self.root, self.handler, self.interval = root, handler, interval_ms
        self.q = queue.Queue()
        self._closed = False
        root.after(interval_ms, self._pump)

    def put(self, kind, *args):
        self.q.put((kind, args))

    def call(self, fn):
        """Chạy fn() trên luồng giao diện và chờ kết quả (gọi từ luồng dịch, vd. hộp thoại gợi ý từ điển)."""
        done, box = threading.Event(), {}
        self.q.put(("__call__", (fn, box, done)))
        done.wait()
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def close(self):
        self._closed = True

    def _pump(self):
        if self._closed:
            return
        for _ in range(200):  # tối đa mỗi nhịp, tránh làm đứng giao diện khi log dồn dập
            try:
                kind, args = self.q.get_nowait()
            except queue.Empty:
                break
            if kind == "__call__":
                fn, box, done = args
                try:
                    box["value"] = fn()
                except Exception as e:  # noqa: BLE001
                    box["error"] = e
                finally:
                    done.set()
            else:
                try:
                    self.handler(kind, *args)
                except Exception:  # noqa: BLE001  (lỗi hiển thị không được làm chết vòng lặp)
                    pass
        self.root.after(self.interval, self._pump)
