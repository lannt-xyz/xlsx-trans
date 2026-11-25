"""Gọi Ollama qua HTTP (chỉ dùng thư viện chuẩn). Đây là nơi DUY NHẤT trong app có kết nối mạng,
và chỉ tới địa chỉ cfg.host (mặc định localhost)."""
import json
import urllib.request

from . import metrics


def _http_json(url, payload=None, timeout=600):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_models(host):
    try:
        info = _http_json(f"{host}/api/tags", timeout=5)
        return [m["name"] for m in info.get("models", [])]
    except Exception:
        return []


def build_messages(text, cfg):
    tpl = cfg.user_template
    user = tpl.replace("{text}", text) if "{text}" in tpl else f"{tpl}\n\n{text}"
    msgs = []
    if cfg.system_prompt:
        msgs.append({"role": "system", "content": cfg.system_prompt})
    msgs.append({"role": "user", "content": user})
    return msgs


def translate_text(text, cfg):
    payload = {
        "model": cfg.model,
        "stream": False,
        "options": dict(cfg.options),
        "messages": build_messages(text, cfg),
    }
    if cfg.keep_alive:
        payload["keep_alive"] = cfg.keep_alive
    last_err = None
    for _ in range(cfg.retries + 1):
        try:
            res = _http_json(f"{cfg.host}/api/chat", payload, timeout=cfg.timeout)
            metrics.add(res.get("prompt_eval_count"), res.get("eval_count"), (res.get("eval_duration") or 0) / 1e9)
            out = res["message"]["content"].strip()
            if out:
                return out
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"Ollama lỗi: {last_err}")
