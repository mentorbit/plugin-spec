"""渲染器开发宿主的测试：在本机随机端口启动服务，检查规范 4.2 要求的响应头与路径穿越防护。

用法：python -m unittest discover -s tools -p "test_*.py"
"""

from __future__ import annotations

import http.client
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "renderer_host"))
import serve  # noqa: E402

PACKAGE = HERE.parent / "examples" / "flashcard-renderer"


class RendererHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(PACKAGE, "http://127.0.0.1:0"))
        serve_origin = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.server.RequestHandlerClass = serve.make_handler(PACKAGE, serve_origin)
        cls.origin = serve_origin
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path: str):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp

    def test_host_page_restricts_frames_to_package_origin(self):
        csp = self.get("/").getheader("Content-Security-Policy") or ""
        self.assertIn(f"frame-src {self.origin}", csp)

    def test_renderer_documents_carry_sandbox_csp(self):
        resp = self.get("/plugin/renderer/index.html")
        self.assertEqual(resp.status, 200)
        csp = resp.getheader("Content-Security-Policy") or ""
        for directive in ("default-src 'none'", "connect-src 'none'", f"media-src {self.origin}", "base-uri 'none'"):
            self.assertIn(directive, csp)

    def test_path_traversal_and_directories_rejected(self):
        for path in ("/plugin/../mentorbit.plugin.json", "/plugin/..%2f..%2fREADME.md",
                     "/plugin/%2e%2e/%2e%2e/LICENSE-APACHE", "/plugin/renderer/"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status, 404)


if __name__ == "__main__":
    unittest.main()
