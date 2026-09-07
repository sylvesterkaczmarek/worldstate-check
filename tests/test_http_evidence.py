import io
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from worldstate_check import Verdict, verify_spec_data
from worldstate_check.models import CheckStatus
from worldstate_check.report import write_json_report


@contextmanager
def endpoint(body=b'{"ready":true}', status=200):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/health", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def verify_http(tmp_path, url, **assertions):
    return verify_spec_data(
        {"version": 1, "task": "HTTP evidence", "checks": [
            {"id": "http", "type": "http", "url": url, **assertions},
        ]},
        root=tmp_path,
        allow_network=True,
    )


def assert_report_redacted(tmp_path, report, safe_url):
    assert report.results[0].evidence["url"] == safe_url
    report_path = write_json_report(report, tmp_path / "report.json")
    serialized = report_path.read_text(encoding="utf-8")
    for secret in ("SYNTHETIC_TOKEN", "SYNTHETIC_FRAGMENT", "SYNTHETIC_PASSWORD", "SYNTHETIC_USER"):
        assert secret not in serialized


@pytest.mark.parametrize("status", [200, 503])
def test_public_http_report_redacts_url_and_closes_response(tmp_path, monkeypatch, status):
    urlopen = urllib.request.urlopen
    responses = []

    def tracked_urlopen(*args, **kwargs):
        try:
            response = urlopen(*args, **kwargs)
        except urllib.error.HTTPError as exc:
            responses.append(exc)
            raise
        responses.append(response)
        return response

    monkeypatch.setattr(urllib.request, "urlopen", tracked_urlopen)
    with endpoint(status=status) as (url, requests):
        report = verify_http(
            tmp_path,
            url + "?token=SYNTHETIC_TOKEN#SYNTHETIC_FRAGMENT",
            status=status,
            json_field="ready",
            operator="eq",
            value=True,
        )

    assert report.verdict is Verdict.VERIFIED
    assert report.results[0].observed["status"] == status
    assert requests == ["/health?token=SYNTHETIC_TOKEN"]
    assert_report_redacted(tmp_path, report, url)
    assert len(responses) == 1
    assert responses[0].closed


@pytest.mark.parametrize("failure", ["connection", "read", "http_error_read"])
def test_url_bearing_transport_errors_do_not_leak_and_close_response(tmp_path, monkeypatch, failure):
    url = "http://SYNTHETIC_USER:SYNTHETIC_PASSWORD@127.0.0.1:1234/health?token=SYNTHETIC_TOKEN#SYNTHETIC_FRAGMENT"

    class BrokenResponse(io.BytesIO):
        status = 200

        def read(self, *args):
            raise urllib.error.URLError(f"could not read {url}")

    response = BrokenResponse()

    def failing_urlopen(request, **kwargs):
        assert request.full_url == url
        if failure == "connection":
            raise urllib.error.URLError(f"could not open {url}")
        if failure == "http_error_read":
            raise urllib.error.HTTPError(url, 503, f"unavailable: {url}", {}, response)
        return response

    monkeypatch.setattr(urllib.request, "urlopen", failing_urlopen)
    report = verify_http(tmp_path, url, status=200)

    assert report.results[0].status is CheckStatus.FAIL
    assert report.verdict is Verdict.NOT_VERIFIED
    assert_report_redacted(tmp_path, report, "http://127.0.0.1:1234/health")
    if failure != "connection":
        assert response.closed


@pytest.mark.parametrize(
    "body,expected",
    [
        (b'{"ready":false,"ready":true}', True),
        (b'{"ready":true,"other":NaN}', True),
        (b'{"ready":true,"other":Infinity}', True),
        (b'{"ready":true,"other":-Infinity}', True),
        (b'{"ready":true,"other":1e999}', True),
        (b'{"ready":"\xff"}', "\ufffd"),
    ],
)
def test_public_http_json_requires_unambiguous_utf8_json(tmp_path, body, expected):
    with endpoint(body=body) as (url, _):
        report = verify_http(tmp_path, url, json_field="ready", operator="eq", value=expected)

    assert report.results[0].status is CheckStatus.UNKNOWN
    assert report.verdict is Verdict.UNCERTAIN
    write_json_report(report, tmp_path / "report.json")


def test_text_only_http_retains_replacement_decoding(tmp_path):
    with endpoint(body=b"ready\xff") as (url, _):
        report = verify_http(tmp_path, url, status=200, text_contains="ready\ufffd")
    assert report.verdict is Verdict.VERIFIED


@pytest.mark.parametrize("assertions", [{"status": 200}, {"text_contains": "ready"}])
def test_invalid_json_does_not_hide_observed_failure(tmp_path, assertions):
    with endpoint(body=b"not JSON", status=503) as (url, _):
        report = verify_http(
            tmp_path, url, json_field="ready", operator="eq", value=True, **assertions,
        )
    assert report.verdict is Verdict.NOT_VERIFIED
    result = report.results[0]
    assert result.status is CheckStatus.FAIL
    assert result.observed["status"] == 503
    assert "JSON assertion could not be evaluated" in result.summary


@pytest.mark.parametrize("status,expected_verdict", [(200, Verdict.UNCERTAIN), (503, Verdict.NOT_VERIFIED)])
def test_response_limit_preserves_status_failure_and_closes_response(tmp_path, monkeypatch, status, expected_verdict):
    response = io.BytesIO(b"x" * 1_048_577)
    response.status = status
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: response)
    report = verify_http(tmp_path, "http://127.0.0.1:1234/health", status=200)
    assert report.verdict is expected_verdict
    assert response.closed


def test_json_parser_errors_do_not_echo_url_bearing_response_keys(tmp_path):
    key = "http://SYNTHETIC_USER:SYNTHETIC_PASSWORD@host/path?token=SYNTHETIC_TOKEN#SYNTHETIC_FRAGMENT"
    body = ('{"' + key + '":false,"' + key + '":true,"ready":true}').encode()
    with endpoint(body=body) as (url, _):
        report = verify_http(tmp_path, url, json_field="ready", operator="eq", value=True)
    assert report.verdict is Verdict.UNCERTAIN
    assert_report_redacted(tmp_path, report, url)
