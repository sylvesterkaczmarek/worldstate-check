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
    return VerificationContext(spec_path=tmp_path / "spec.yaml", root=tmp_path, allow_network=True)


def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def test_network_checks_disabled_by_default(tmp_path):
    disabled = VerificationContext(spec_path=tmp_path / "spec.yaml", root=tmp_path)
    http_check = {"id": "h", "type": "http", "url": "http://127.0.0.1:1/", "status": 200}
    tcp_check = {"id": "t", "type": "tcp", "host": "127.0.0.1", "port": 1}
    assert run_http_check(http_check, disabled).status is CheckStatus.UNKNOWN
    assert run_tcp_check(tcp_check, disabled).status is CheckStatus.UNKNOWN


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


def test_http_evidence_redacts_query_and_credentials(tmp_path):
    from worldstate_check.util import redact_url_for_evidence

    redacted = redact_url_for_evidence("https://user:secret@example.com:8443/health?token=abc#fragment")
    assert redacted == "https://example.com:8443/health"
    assert "secret" not in redacted
    assert "token" not in redacted
