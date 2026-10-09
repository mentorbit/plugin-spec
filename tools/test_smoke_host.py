"""冒烟宿主的宿主方法测试：不启动插件进程，直接驱动 Host 的回调处理与调用流程。

用法：python -m unittest discover -s tools -p "test_*.py"
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_tool  # noqa: E402


TIMEOUT = "TIMEOUT"  # 脚本标记：这一次等待超时，没有收到消息


class FakeHost(smoke_tool.Host):
    """跳过进程启动，记录发给插件的消息；recv 依次返回预设的插件消息，并记录每次的等待时长。"""

    def __init__(self, grants: list[str], manifest: dict | None = None, script: list | None = None):
        self.grants = grants
        self.manifest = manifest or {}
        self.storage = {}
        self.active_calls = {}
        self.sent: list[dict] = []
        self.script = list(script or [])
        self.waits: list[float] = []
        self.next_id = 0

    def send(self, message: dict) -> None:
        self.sent.append(message)

    def recv(self, timeout: float = 5.0) -> dict:
        self.waits.append(timeout)
        if not self.script or self.script[0] == TIMEOUT:
            if self.script:
                self.script.pop(0)
            raise smoke_tool.RecvTimeout(f"{timeout} 秒内没有收到插件消息")
        return self.script.pop(0)


def reason(message: dict) -> str | None:
    return message.get("error", {}).get("data", {}).get("reason")


class HostMethodTests(unittest.TestCase):
    def setUp(self):
        self.host = FakeHost(["storage.plugin", "network:https://api.example.com", "learner.read:knowledge"])
        self.host.active_calls["call-rw"] = {"learner": "learner-1", "effect": "creates_object"}
        self.host.active_calls["call-ro"] = {"learner": "learner-1", "effect": "read_only"}

    def answer(self, method: str, params: dict) -> dict:
        self.host.answer_host_request({"jsonrpc": "2.0", "id": "h1", "method": method, "params": params}, [])
        return self.host.sent[-1]

    def test_definition_naming(self):
        self.assertEqual(smoke_tool.host_method_def("host/storage.get", "Params"), "storageGetParams")
        self.assertEqual(smoke_tool.host_method_def("host/evidence.propose", "Result"), "evidenceProposeResult")

    def test_storage_roundtrip_and_delete(self):
        self.assertEqual(self.answer("host/storage.set", {"callId": "call-rw", "key": "k", "value": [1]})["result"], {})
        self.assertEqual(self.answer("host/storage.get", {"callId": "call-rw", "key": "k"})["result"], {"value": [1]})
        self.assertEqual(self.answer("host/storage.delete", {"callId": "call-rw", "key": "k"})["result"], {})
        self.assertEqual(self.answer("host/storage.get", {"callId": "call-rw", "key": "k"})["result"], {"value": None})

    def test_read_only_tool_cannot_write_storage(self):
        self.assertEqual(reason(self.answer("host/storage.set", {"callId": "call-ro", "key": "k", "value": 1})), "permission_denied")
        self.assertEqual(reason(self.answer("host/storage.delete", {"callId": "call-ro", "key": "k"})), "permission_denied")
        self.assertIn("result", self.answer("host/storage.get", {"callId": "call-ro", "key": "k"}))

    def test_unknown_call_id_denied(self):
        self.assertEqual(reason(self.answer("host/storage.get", {"callId": "ended", "key": "k"})), "permission_denied")

    def test_ungranted_permission_denied(self):
        msg = self.answer("host/model.invoke", {"callId": "call-rw", "messages": [{"role": "user", "content": "hi"}], "maxTokens": 16})
        self.assertEqual(reason(msg), "permission_denied")
        self.assertEqual(reason(self.answer("host/learner.read", {"callId": "call-rw", "dimension": "human"})), "permission_denied")

    def test_network_origin_matching(self):
        def fetch(url):
            return reason(self.answer("host/http.fetch", {"callId": "call-rw", "url": url, "method": "GET"}))
        # 已授权的源通过授权检查（冒烟宿主未实现网络请求，因而返回 method_not_found）
        self.assertEqual(fetch("https://api.example.com/terms?q=1"), "method_not_found")
        self.assertEqual(fetch("https://api.example.com.evil.com/"), "permission_denied")
        self.assertEqual(fetch("https://other.example.com/"), "permission_denied")

    def test_invalid_params_rejected(self):
        with self.assertRaises(smoke_tool.CheckFailed):
            self.answer("host/http.fetch", {"callId": "call-rw", "url": "http://api.example.com/", "method": "GET"})
        with self.assertRaises(smoke_tool.CheckFailed):
            self.answer("host/learner.read", {"callId": "call-rw", "dimension": "mood"})

    def test_unknown_method(self):
        self.assertEqual(reason(self.answer("host/filesystem.read", {"callId": "call-rw"})), "method_not_found")


class ReadOnlyResultTests(unittest.TestCase):
    MANIFEST = {"contributes": {"tools": [{
        "id": "peek", "effect": "read_only", "timeoutMs": 1000,
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    }]}}

    def call_with_result(self, result: dict):
        host = FakeHost([], self.MANIFEST, script=[{"jsonrpc": "2.0", "id": "q1", "result": result}])
        return host.call_tool("peek", {})

    def test_read_only_without_objects_passes(self):
        out = self.call_with_result({"summary": "ok"})
        self.assertEqual(out["message"]["result"]["summary"], "ok")

    def test_read_only_with_objects_fails(self):
        with self.assertRaises(smoke_tool.CheckFailed):
            self.call_with_result({"summary": "ok", "objects": [{"objectType": "x_y", "value": {}, "fallbackText": "x"}]})


class TimeoutTests(unittest.TestCase):
    """规范 5.4：宿主按工具声明的 timeoutMs 等待，超时后发送 $/cancel。"""

    @staticmethod
    def manifest(timeout_ms: int) -> dict:
        return {"contributes": {"tools": [{
            "id": "slow", "effect": "creates_object", "timeoutMs": timeout_ms,
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        }]}}

    def test_waits_for_declared_timeout_not_a_fixed_value(self):
        host = FakeHost([], self.manifest(10_000), script=[{"jsonrpc": "2.0", "id": "q1", "result": {"summary": "ok"}}])
        host.call_tool("slow", {})
        self.assertGreater(host.waits[0], 9.0)
        self.assertLessEqual(host.waits[0], 10.0)

    def test_timeout_sends_cancel_then_fails(self):
        host = FakeHost([], self.manifest(1_000), script=[TIMEOUT, TIMEOUT])
        with self.assertRaises(smoke_tool.CheckFailed) as ctx:
            host.call_tool("slow", {})
        cancels = [m for m in host.sent if m.get("method") == "$/cancel"]
        self.assertEqual(len(cancels), 1)
        self.assertEqual(host.waits[1], smoke_tool.CANCEL_GRACE_SECONDS)
        self.assertIn("timeoutMs=1000", str(ctx.exception))
        self.assertNotIn(cancels[0]["params"]["callId"], host.active_calls)

    def test_timeout_reports_late_cancelled_response(self):
        cancelled = {"jsonrpc": "2.0", "id": "q1",
                     "error": {"code": -32004, "message": "cancelled", "data": {"reason": "cancelled"}}}
        host = FakeHost([], self.manifest(1_000), script=[TIMEOUT, cancelled])
        with self.assertRaises(smoke_tool.CheckFailed) as ctx:
            host.call_tool("slow", {})
        self.assertIn("cancelled", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
