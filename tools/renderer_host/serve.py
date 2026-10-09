"""渲染器开发宿主：在本机按规范第 04 章的沙箱要求加载一个渲染器，便于插件作者调试。

用法：python tools/renderer_host/serve.py <插件包目录> [--port 8765]
然后用浏览器打开 http://127.0.0.1:8765/

/plugin/ 下的包文件带有规范 4.2 要求的内容安全策略；宿主页面用只含 allow-scripts 的
sandbox iframe 加载渲染器。仅供本机开发使用，只监听 127.0.0.1。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent


def make_handler(package: Path, origin: str):
    package = package.resolve()
    manifest = json.loads((package / "mentorbit.plugin.json").read_text(encoding="utf-8"))
    # 规范 4.2：渲染器文档的 CSP
    csp = (
        f"default-src 'none'; script-src {origin}; style-src {origin} 'unsafe-inline'; "
        f"img-src {origin} data: blob:; media-src {origin}; font-src {origin}; connect-src 'none'; "
        "form-action 'none'; base-uri 'none'"
    )
    # 规范 4.2：宿主页面用 frame-src 把渲染器 iframe 限制在包资源源以内，阻止其跳转到外部页面
    host_csp = (
        f"default-src 'self'; style-src 'self' 'unsafe-inline'; frame-src {origin}; "
        "object-src 'none'; form-action 'none'; base-uri 'none'"
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # 只输出到标准错误，保持简洁
            sys.stderr.write("[serve] " + fmt % args + "\n")

        def send_bytes(self, body: bytes, content_type: str, extra: dict | None = None):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            if path == "/":
                return self.send_bytes((HERE / "host.html").read_bytes(), "text/html; charset=utf-8",
                                       {"Content-Security-Policy": host_csp})
            if path == "/host.js":
                return self.send_bytes((HERE / "host.js").read_bytes(), "text/javascript; charset=utf-8")
            if path == "/manifest.json":
                return self.send_bytes(json.dumps(manifest, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            if path.startswith("/plugin/"):
                rel = path[len("/plugin/"):]
                target = (package / rel).resolve()
                # 规范 1.1：不得越出包目录
                if package not in target.parents or not target.is_file():
                    return self.send_error(404)
                ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                    ctype += "; charset=utf-8"
                return self.send_bytes(target.read_bytes(), ctype, {"Content-Security-Policy": csp, "X-Content-Type-Options": "nosniff"})
            self.send_error(404)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    origin = f"http://127.0.0.1:{args.port}"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(Path(args.package), origin))
    print(f"渲染器开发宿主已启动：{origin}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
