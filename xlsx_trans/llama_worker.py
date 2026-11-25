"""Tiến trình con nạp và chạy model llama.cpp. App chính nói chuyện qua stdin/stdout (mỗi dòng một JSON).

Chạy tách riêng để: (1) lỗi native của llama.cpp (access violation...) không làm hỏng tiến trình giao diện,
(2) model chạy trong một tiến trình "sạch", không lẫn với Tk / lxml / các thư viện khác của app.
Không import gì của xlsx_trans ngoài file này.
"""
import json
import os
import sys


def main():
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)  # mọi thứ in ra stdout (kể cả từ thư viện native) đi sang stderr, không phá giao thức

    def send(obj):
        proto.write(json.dumps(obj, ensure_ascii=True) + "\n")
        proto.flush()

    llm = None
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            op = req.get("op")
            if op == "quit":
                break
            if op == "load":
                from llama_cpp import Llama

                llm = Llama(**req["kwargs"])
                send({"ok": True})
            elif op == "chat":
                if llm is None:
                    raise RuntimeError("Model chưa được nạp.")
                send({"ok": True, "res": llm.create_chat_completion(messages=req["messages"], **req["params"])})
            else:
                raise ValueError(f"op không hợp lệ: {op!r}")
        except BaseException as e:  # noqa: BLE001
            send({"ok": False, "error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
