"""术语速查工具：演示 mentorbit.tool/0.1 运行协议（见规范第 05 章）。

只依赖标准库。每条 tools/call 在独立线程中处理，处理期间可以回调宿主的 host/* 方法；
主线程负责读取标准输入并分派请求、通知和宿主响应。
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

PROTOCOL = "mentorbit.tool/0.1"
TOOLS = ["lookup_term"]
DATA = json.loads((Path(__file__).resolve().parent.parent / "data" / "terms.json").read_text(encoding="utf-8"))

ERRORS = {
    "parse_error": -32700,
    "invalid_request": -32600,
    "invalid_params": -32602,
    "method_not_found": -32601,
    "internal_error": -32603,
    "cancelled": -32004,
}

_out_lock = threading.Lock()
_state_lock = threading.Lock()
_grants: set[str] = set()
_calls: dict[str, threading.Event] = {}  # callId -> 取消标记
_host_pending: dict[str, dict] = {}  # 发往宿主的请求 id -> {"event", "message"}
_next_host_id = 0


class Cancelled(Exception):
    pass


class HostError(Exception):
    def __init__(self, error: dict):
        super().__init__(error.get("message", ""))
        self.reason = (error.get("data") or {}).get("reason")


def send(message: dict) -> None:
    line = json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False) + "\n"
    with _out_lock:
        sys.stdout.buffer.write(line.encode("utf-8"))
        sys.stdout.buffer.flush()


def send_error(request_id, reason: str, message: str) -> None:
    send({"id": request_id, "error": {"code": ERRORS[reason], "message": message, "data": {"reason": reason}}})


def host_call(call_id: str, method: str, params: dict) -> dict:
    """向宿主发请求并等待响应；调用被取消时抛出 Cancelled。"""
    global _next_host_id
    cancelled = _calls[call_id]
    with _state_lock:
        _next_host_id += 1
        request_id = f"h{_next_host_id}"
        waiter = {"event": threading.Event(), "message": None}
        _host_pending[request_id] = waiter
    send({"id": request_id, "method": method, "params": {"callId": call_id, **params}})
    while not waiter["event"].wait(0.05):
        if cancelled.is_set():
            with _state_lock:
                _host_pending.pop(request_id, None)
            raise Cancelled()
    if cancelled.is_set():
        raise Cancelled()
    message = waiter["message"]
    if "error" in message:
        raise HostError(message["error"])
    return message["result"]


def find_term(term: str) -> tuple[str, dict] | None:
    key = term.strip().lower()
    for name, entry in DATA.items():
        if key == name.lower() or key in (alias.lower() for alias in entry["aliases"]):
            return name, entry
    return None


def remember(call_id: str, term: str) -> None:
    """记录最近查询；storage.plugin 是可选权限，未授权或被撤销时静默跳过。"""
    if "storage.plugin" not in _grants:
        return
    try:
        recent = host_call(call_id, "host/storage.get", {"key": "recent"}).get("value") or []
        recent = [t for t in recent if t != term][-9:] + [term]
        host_call(call_id, "host/storage.set", {"key": "recent", "value": recent})
    except HostError as error:
        if error.reason != "permission_denied":
            raise


def lookup_term(call_id: str, args: dict) -> dict:
    term = args.get("term")
    if not isinstance(term, str) or not term.strip():
        raise ValueError("term 必须是非空字符串")
    found = find_term(term)
    if found is None:
        names = "、".join(DATA)
        return {"summary": f"未收录术语「{term}」。目前只收录：{names}。", "isError": True}
    name, entry = found
    remember(call_id, name)
    value = {"term": name, "definition": entry["definition"], "example": entry["example"], "pitfalls": entry["pitfalls"]}
    summary = f"术语「{name}」：{entry['definition']} 例子：{entry['example']} 常见误区：{'；'.join(entry['pitfalls'])}。"
    return {
        "summary": summary,
        "objects": [{"objectType": "glossary_entry", "value": value, "fallbackText": f"{name}：{entry['definition']}"}],
    }


def handle_call(request_id, params: dict) -> None:
    call_id = params["callId"]
    try:
        if params.get("toolId") != "lookup_term":
            send_error(request_id, "invalid_params", f"未知工具 {params.get('toolId')}")
            return
        result = lookup_term(call_id, params.get("input") or {})
        if _calls[call_id].is_set():
            raise Cancelled()
        send({"id": request_id, "result": result})
    except Cancelled:
        send_error(request_id, "cancelled", "调用已取消")
    except ValueError as error:
        send_error(request_id, "invalid_params", str(error))
    except Exception as error:  # 兜底：不让单次调用拖垮整个进程
        send_error(request_id, "internal_error", f"{type(error).__name__}: {error}")
    finally:
        with _state_lock:
            _calls.pop(call_id, None)


def valid_id(value) -> bool:
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def main() -> None:
    # 规范 5.4：畸形消息按 5.5 回复错误，不退出、不影响其他调用
    for raw in sys.stdin.buffer:
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            send_error(None, "parse_error", "不是合法的 JSON")
            continue
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            rid = message.get("id") if isinstance(message, dict) else None
            send_error(rid if valid_id(rid) else None, "invalid_request", "不是合法的 JSON-RPC 2.0 消息")
            continue

        method = message.get("method")
        request_id = message.get("id")

        if method is None:
            if "result" in message or "error" in message:  # 宿主对 host/* 请求的响应
                with _state_lock:
                    waiter = _host_pending.pop(request_id, None) if valid_id(request_id) else None
                if waiter:
                    waiter["message"] = message
                    waiter["event"].set()
            else:
                send_error(request_id if valid_id(request_id) else None, "invalid_request", "缺少 method")
            continue
        if not isinstance(method, str):
            send_error(request_id if valid_id(request_id) else None, "invalid_request", "method 必须是字符串")
            continue

        params = message.get("params", {})
        if not isinstance(params, dict):
            if request_id is not None:
                send_error(request_id, "invalid_params", "params 必须是对象")
            continue

        if method == "initialize":
            grants = params.get("grants", [])
            if not isinstance(grants, list) or not all(isinstance(g, str) for g in grants):
                send_error(request_id, "invalid_params", "grants 必须是字符串数组")
                continue
            _grants.clear()
            _grants.update(grants)
            send({"id": request_id, "result": {"protocol": PROTOCOL, "tools": TOOLS}})
        elif method == "tools/call":
            call_id = params.get("callId")
            if not isinstance(call_id, str) or not call_id:
                send_error(request_id, "invalid_params", "tools/call 缺少 callId")
                continue
            with _state_lock:
                if call_id in _calls:
                    send_error(request_id, "invalid_params", f"callId 重复：{call_id}")
                    continue
                _calls[call_id] = threading.Event()
            threading.Thread(target=handle_call, args=(request_id, params), daemon=True).start()
        elif method == "$/cancel":
            with _state_lock:
                flag = _calls.get(params.get("callId"))
            if flag:
                flag.set()
        elif method == "shutdown":
            send({"id": request_id, "result": {}})
        elif method == "exit":
            return
        elif request_id is not None:
            send_error(request_id, "method_not_found", f"未知方法 {method}")


if __name__ == "__main__":
    main()
