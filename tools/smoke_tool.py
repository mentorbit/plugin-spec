"""最小宿主：按规范第 05 章启动一个工具插件并跑一组冒烟检查。

用法：python tools/smoke_tool.py <工具插件包目录>

这不是生产宿主，只用来证明协议可以被实现，并检查插件行为：握手、输入校验、
宿主回调（私有存储）、对象校验与封装、业务失败、取消、可选权限被拒、未知方法、关闭。
目前只支持 interpreter 为 python3 的插件。
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent.parent
TOOL_SCHEMA_ID = "https://mentorbit.invalid/spec/0.1/tool-messages.schema.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def build_registry() -> Registry:
    resources = []
    for path in (ROOT / "schemas").rglob("*.json"):
        schema = load_json(path)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


REGISTRY = build_registry()


def validator_for(ref: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": ref}, registry=REGISTRY)


MESSAGE = validator_for(TOOL_SCHEMA_ID)
DEFS = {name: validator_for(f"{TOOL_SCHEMA_ID}#/$defs/{name}") for name in (
    "initializeResult", "toolsCallParams", "toolsCallResult",
)}
ENVELOPE = validator_for("https://mentorbit.invalid/spec/0.1/object-envelope.schema.json")


def host_method_def(method: str, kind: str) -> str:
    """规范 4.5 / 5.4：去掉 host/ 前缀，按 / 与 . 分段驼峰拼接，例如 host/storage.get -> storageGetParams。"""
    parts = re.split(r"[/.]", method.removeprefix("host/"))
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:]) + kind


# 宿主方法 -> 所需权限（规范 5.4 表格）；带冒号的按前缀匹配，参数决定后缀
HOST_PERMISSIONS = {
    "host/storage.get": "storage.plugin",
    "host/storage.set": "storage.plugin",
    "host/storage.delete": "storage.plugin",
    "host/model.invoke": "model.invoke",
    "host/http.fetch": "network:",
    "host/context.message": "context.read:message",
    "host/objects.read": "objects.read:",
    "host/learner.read": "learner.read:",
    "host/evidence.propose": "evidence.propose:",
}
STORAGE_WRITES = {"host/storage.set", "host/storage.delete"}


class CheckFailed(Exception):
    pass


class RecvTimeout(CheckFailed):
    """在给定时间内没有收到插件消息。"""


CANCEL_GRACE_SECONDS = 2.0  # 规范 5.4：发送 $/cancel 后等待插件响应的时间


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def assert_valid(validator: Draft202012Validator, instance, what: str) -> None:
    errors = [e.message for e in validator.iter_errors(instance)]
    expect(not errors, f"{what} 不符合 Schema：{errors[:3]}")


class Host:
    """一个插件进程的宿主侧连接。"""

    def __init__(self, package: Path, manifest: dict, grants: list[str]):
        self.package = package
        self.manifest = manifest
        self.grants = grants
        self.storage: dict[tuple[str, str], object] = {}
        self.active_calls: dict[str, dict] = {}  # callId -> {"learner", "effect"}
        self.inbox: queue.Queue = queue.Queue()
        self.next_id = 0
        self.tmp = tempfile.TemporaryDirectory(prefix="mentorbit-tool-")
        runtime = manifest["runtime"]
        if runtime["interpreter"] != "python3":
            raise CheckFailed(f"本冒烟宿主只支持 python3，插件声明的是 {runtime['interpreter']}")
        entry = (package / runtime["entry"]).resolve()
        # 规范 5.4：只提供必要的环境变量，不传宿主凭据；不经过 shell
        env = {"MENTORBIT_TMPDIR": self.tmp.name, "PYTHONIOENCODING": "utf-8"}
        if os.name == "nt":
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
        self.proc = subprocess.Popen(
            [sys.executable, "-I", str(entry)],
            cwd=package, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for raw in self.proc.stdout:
            try:
                message = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                message = {"__invalid__": raw[:200]}
            self.inbox.put(message)
        self.inbox.put(None)

    def send(self, message: dict) -> None:
        line = json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        self.proc.stdin.flush()

    def request(self, method: str, params: dict) -> str:
        self.next_id += 1
        request_id = f"q{self.next_id}"
        self.send({"id": request_id, "method": method, "params": params})
        return request_id

    def recv(self, timeout: float = 5.0) -> dict:
        try:
            message = self.inbox.get(timeout=timeout)
        except queue.Empty:
            raise RecvTimeout(f"{timeout:.1f} 秒内没有收到插件消息")
        expect(message is not None, "插件进程意外退出")
        expect("__invalid__" not in message, f"插件输出了非 JSON 行：{message.get('__invalid__')!r}")
        assert_valid(MESSAGE, message, "插件消息")
        return message

    def answer_host_request(self, message: dict, seen: list[str]) -> None:
        """实现宿主方法：校验 callId 与授权，再执行（规范 5.4 宿主提供的方法）。"""
        method, params, request_id = message["method"], message.get("params", {}), message["id"]
        seen.append(method)

        def deny(reason="permission_denied", code=-32001):
            self.send({"id": request_id, "error": {"code": code, "message": reason, "data": {"reason": reason}}})

        if method not in HOST_PERMISSIONS:
            return deny("method_not_found", -32601)
        assert_valid(validator_for(f"{TOOL_SCHEMA_ID}#/$defs/{host_method_def(method, 'Params')}"), params, f"{method} 参数")
        call = self.active_calls.get(params.get("callId"))
        if call is None:
            return deny()
        # 规范 5.3：read_only 工具不得写存储
        if method in STORAGE_WRITES and call["effect"] == "read_only":
            return deny()
        permission = HOST_PERMISSIONS[method]
        suffix = {"host/objects.read": "objectType", "host/learner.read": "dimension",
                  "host/evidence.propose": "eventType"}.get(method)
        if suffix:
            permission += params[suffix]
        if method == "host/http.fetch":
            # 只放行已授权的源：URL 必须恰好是该源，或在源之后紧跟 / 或 ?，防止 example.com.evil.com 这类前缀冒充
            origins = [g[len("network:"):] for g in self.grants if g.startswith("network:")]
            granted = any(params["url"] == o or params["url"].startswith((o + "/", o + "?")) for o in origins)
        else:
            granted = permission in self.grants
        if not granted:
            return deny()

        key = (call["learner"], params.get("key"))
        if method == "host/storage.get":
            result = {"value": self.storage.get(key)}
        elif method == "host/storage.set":
            self.storage[key] = params["value"]
            result = {}
        elif method == "host/storage.delete":
            self.storage.pop(key, None)
            result = {}
        else:
            return deny("method_not_found", -32601)  # 冒烟宿主只实现存储，其余方法在授权检查后拒绝
        assert_valid(validator_for(f"{TOOL_SCHEMA_ID}#/$defs/{host_method_def(method, 'Result')}"), result, f"{method} 结果")
        self.send({"id": request_id, "result": result})

    def call_tool(self, tool_id: str, tool_input: dict, learner: str = "learner-ref-0001", hold_host=False):
        """发起 tools/call 并处理期间的宿主回调。hold_host=True 时在第一个回调处暂停，返回控制权。"""
        tool = next(t for t in self.manifest["contributes"]["tools"] if t["id"] == tool_id)
        # 规范 5.4：宿主先按 inputSchema 校验输入，再交给插件
        errors = list(Draft202012Validator(tool["inputSchema"]).iter_errors(tool_input))
        if errors:
            return {"rejectedByHost": [e.message for e in errors]}
        call_id = uuid.uuid4().hex
        params = {
            "callId": call_id, "toolId": tool_id, "input": tool_input,
            "scope": {"learnerRef": learner, "sessionRef": "session-ref-0001", "locale": "zh-CN"},
            "timeoutMs": tool.get("timeoutMs", 30000),
        }
        assert_valid(DEFS["toolsCallParams"], params, "tools/call 参数")
        self.active_calls[call_id] = {"learner": learner, "effect": tool["effect"]}
        request_id = self.request("tools/call", params)
        seen: list[str] = []
        # 规范 5.4：按工具声明的 timeoutMs 等待；超时后发送 $/cancel，再等待片刻
        deadline = time.monotonic() + params["timeoutMs"] / 1000
        try:
            while True:
                try:
                    message = self.recv(timeout=max(0.0, deadline - time.monotonic()))
                except RecvTimeout:
                    self.send({"method": "$/cancel", "params": {"callId": call_id}})
                    try:
                        late = self.recv(timeout=CANCEL_GRACE_SECONDS)
                        detail = f"插件随后返回：{late.get('error', {}).get('data', {}).get('reason') or '结果'}"
                    except RecvTimeout:
                        detail = f"发送 $/cancel 后 {CANCEL_GRACE_SECONDS:.0f} 秒内仍无响应，宿主可以终止进程"
                    raise CheckFailed(f"工具 {tool_id} 超过声明的 timeoutMs={params['timeoutMs']}；{detail}")
                if "method" in message and "id" in message:
                    if hold_host:
                        return {"callId": call_id, "requestId": request_id, "held": message, "seen": seen}
                    self.answer_host_request(message, seen)
                    continue
                expect(message.get("id") == request_id, f"收到不属于本次调用的消息：{message}")
                # 规范 5.3：read_only 工具产出对象时，宿主丢弃对象并视为失败
                if tool["effect"] == "read_only":
                    expect(not message.get("result", {}).get("objects"), "read_only 工具不得产出对象")
                return {"callId": call_id, "message": message, "seen": seen}
        finally:
            if not hold_host:
                self.active_calls.pop(call_id, None)

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        self.tmp.cleanup()


def envelope(manifest: dict, obj: dict) -> dict:
    """宿主为插件产出的对象补全信封字段（规范 5.2）。"""
    object_type = next(o for o in manifest["contributes"]["objectTypes"] if o["id"] == obj["objectType"])
    return {
        "objectType": f"{manifest['id']}/{obj['objectType']}",
        "schemaVersion": object_type["schemaVersion"],
        "objectId": uuid.uuid4().hex,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "producer": {"pluginId": manifest["id"], "pluginVersion": manifest["version"]},
        "supersedes": None,
        "fallbackText": obj["fallbackText"],
        "value": obj["value"],
    }


def run(package: Path) -> int:
    manifest = load_json(package / "mentorbit.plugin.json")
    tools = manifest["contributes"].get("tools", [])
    if not tools:
        print("该插件没有工具贡献")
        return 2
    declared = sorted(t["id"] for t in tools)
    object_validators = {
        o["id"]: Draft202012Validator(load_json(package / o["schema"]))
        for o in manifest["contributes"].get("objectTypes", [])
    }
    optional = {p["id"] for p in manifest.get("permissions", []) if p.get("optional")}
    all_grants = [p["id"] for p in manifest.get("permissions", [])]
    results: list[tuple[str, bool, str]] = []
    host = Host(package, manifest, all_grants)

    def check(name: str, fn) -> None:
        try:
            detail = fn() or ""
            results.append((name, True, detail))
        except CheckFailed as exc:
            results.append((name, False, str(exc)))

    def initialize(h: Host) -> str:
        rid = h.request("initialize", {
            "protocol": "mentorbit.tool/0.1",
            "plugin": {"id": manifest["id"], "version": manifest["version"]},
            "grants": h.grants, "locale": "zh-CN", "limits": {"maxConcurrentCalls": 4},
        })
        message = h.recv()
        expect(message.get("id") == rid and "result" in message, f"initialize 失败：{message}")
        assert_valid(DEFS["initializeResult"], message["result"], "initialize 结果")
        expect(sorted(message["result"]["tools"]) == declared,
               f"实现的工具 {message['result']['tools']} 与清单声明 {declared} 不一致")
        return f"授权 {h.grants or '无'}"

    def happy_path() -> str:
        out = host.call_tool("lookup_term", {"term": "变量"})
        message = out["message"]
        expect("result" in message, f"调用失败：{message}")
        result = message["result"]
        assert_valid(DEFS["toolsCallResult"], result, "tools/call 结果")
        expect(not result.get("isError"), "不应是业务失败")
        expect(out["seen"] == ["host/storage.get", "host/storage.set"], f"宿主回调顺序不符：{out['seen']}")
        for obj in result.get("objects", []):
            expect(obj["objectType"] in object_validators, f"产出了未声明的对象类型 {obj['objectType']}")
            assert_valid(object_validators[obj["objectType"]], obj["value"], f"对象 {obj['objectType']}")
            assert_valid(ENVELOPE, envelope(manifest, obj), "对象信封")
        stored = host.storage.get(("learner-ref-0001", "recent"))
        expect(stored == ["变量"], f"私有存储内容不符：{stored}")
        return f"{len(result.get('objects', []))} 个对象；回调 {out['seen']}"

    def host_rejects_bad_input() -> str:
        out = host.call_tool("lookup_term", {})
        expect("rejectedByHost" in out, "宿主应在调用前拒绝缺少 term 的输入")
        out = host.call_tool("lookup_term", {"term": "变量", "extra": 1})
        expect("rejectedByHost" in out, "宿主应拒绝多余字段")
        return "缺字段与多余字段均在宿主侧拦截"

    def business_failure() -> str:
        out = host.call_tool("lookup_term", {"term": "量子纠缠"})
        result = out["message"].get("result")
        expect(result is not None and result.get("isError") is True, f"未收录的术语应返回 isError：{out['message']}")
        return result["summary"]

    def cancellation() -> str:
        out = host.call_tool("lookup_term", {"term": "函数"}, hold_host=True)
        expect("held" in out, f"预期插件先回调存储，实际：{out}")
        host.send({"method": "$/cancel", "params": {"callId": out["callId"]}})
        started = time.monotonic()
        message = host.recv()
        expect(message.get("id") == out["requestId"], f"收到意外消息：{message}")
        expect(message.get("error", {}).get("code") == -32004, f"应返回 cancelled 错误：{message}")
        elapsed = time.monotonic() - started
        expect(elapsed < 2.0, f"取消响应用时 {elapsed:.2f}s，超过 2 秒")
        # 调用已结束：迟到的回调响应应被插件忽略，宿主按规范对失效 callId 拒绝
        host.active_calls.pop(out["callId"], None)
        host.answer_host_request(out["held"], [])
        return f"{elapsed * 1000:.0f} ms 内返回 cancelled"

    def unknown_method() -> str:
        rid = host.request("tools/frobnicate", {})
        message = host.recv()
        expect(message.get("id") == rid and message.get("error", {}).get("code") == -32601, f"应返回 method_not_found：{message}")
        return "返回 -32601"

    def shutdown(h: Host) -> str:
        rid = h.request("shutdown", {})
        message = h.recv()
        expect(message.get("id") == rid and message.get("result") == {}, f"shutdown 应返回空对象：{message}")
        h.send({"method": "exit"})
        try:
            code = h.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            raise CheckFailed("exit 后 5 秒内未退出")
        expect(code == 0, f"退出码 {code}")
        return "已在 5 秒内正常退出"

    try:
        check("握手 initialize", lambda: initialize(host))
        check("宿主校验输入", host_rejects_bad_input)
        check("正常调用、存储回调与对象校验", happy_path)
        check("业务失败 isError", business_failure)
        check("取消 $/cancel", cancellation)
        check("未知方法", unknown_method)
        check("关闭 shutdown/exit", lambda: shutdown(host))
    finally:
        host.close()

    if optional:
        # 规范 2.2：可选权限被拒绝时插件必须仍能工作
        degraded = Host(package, manifest, [g for g in all_grants if g not in optional])

        def without_optional() -> str:
            out = degraded.call_tool("lookup_term", {"term": "循环"})
            expect("result" in out["message"], f"调用失败：{out['message']}")
            expect(not out["seen"], f"未授权时不应回调 {out['seen']}")
            return f"拒绝 {sorted(optional)} 后仍正常返回"

        try:
            check("可选权限被拒：握手", lambda: initialize(degraded))
            check("可选权限被拒：调用", without_optional)
            check("可选权限被拒：关闭", lambda: shutdown(degraded))
        finally:
            degraded.close()

    print(f"冒烟检查：{manifest['id']} {manifest['version']}")
    for name, ok, detail in results:
        print(f"  {'✓' if ok else '✗'} {name}：{detail}")
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(run(Path(sys.argv[1]).resolve()))
