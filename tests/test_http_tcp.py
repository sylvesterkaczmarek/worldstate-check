import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from worldstate_check.checks.http import run_http_check
from worldstate_check.checks.tcp import run_tcp_check
from worldstate_check.models import CheckStatus, VerificationContext


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"status": "ready", "load": 0.2}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def ctx(tmp_path):
    return VerificationContext(spec_path=tmp_path / "spec.yaml", root=tmp_path)


def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def test_http_status_and_json(tmp_path):
    httpd = server()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/health"
        check = {"id": "h", "type": "http", "url": url, "status": 200, "json_field": "status", "operator": "eq", "value": "ready"}
        assert run_http_check(check, ctx(tmp_path)).status is CheckStatus.PASS
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_unreachable_is_fail(tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    check = {"id": "h", "type": "http", "url": f"http://127.0.0.1:{port}/", "status": 200, "timeout_seconds": 0.2}
    assert run_http_check(check, ctx(tmp_path)).status is CheckStatus.FAIL


def test_tcp_reachable(tmp_path):
    httpd = server()
    try:
        check = {"id": "t", "type": "tcp", "host": "127.0.0.1", "port": httpd.server_address[1], "reachable": True}
        assert run_tcp_check(check, ctx(tmp_path)).status is CheckStatus.PASS
    finally:
        httpd.shutdown()
        httpd.server_close()
