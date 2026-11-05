"""Separately designed release checks; synthetic files and owned loopback only."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from threading import Thread

import pytest

from worldstate_check import Verdict, verify_spec_data
from worldstate_check.report import verify_json_report, write_json_report
from worldstate_check.safe_io import read_regular_bytes
from worldstate_check.util import canonical_json, compare_value


def spec(*checks):
    return {'version': 1, 'task': 'independent-review', 'checks': list(checks)}


@contextmanager
def endpoint(headers, body=b'{"ready":true}', status=200):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            for key, value in headers:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/owned'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


@pytest.mark.parametrize('assertion', [{'status': 200}, {'text_contains': 'ready'},
    {'json_field': 'ready', 'operator': 'eq', 'value': True}])
def test_incomplete_declared_http_response_never_verifies(tmp_path, assertion):
    with endpoint([('Content-Length', '100')]) as url:
        report = verify_spec_data(spec({'id': 'http', 'type': 'http', 'url': url, **assertion}), root=tmp_path, allow_network=True)
    assert report.verdict is not Verdict.VERIFIED, 'matching partial bytes cannot establish a completed HTTP response'


@pytest.mark.parametrize('headers', [
    [('Content-Length', '14'), ('Content-Length', '100')],
    [('Content-Length', '-1')], [('Content-Length', 'invalid')],
])
def test_ambiguous_http_length_is_not_verified(tmp_path, headers):
    with endpoint(headers) as url:
        report = verify_spec_data(spec({'id': 'http', 'type': 'http', 'url': url, 'status': 200}), root=tmp_path, allow_network=True)
    assert report.verdict is not Verdict.VERIFIED


@pytest.mark.parametrize('headers', [[('Content-Length', '14')], [], [('Content-Length', '14'), ('Content-Length', '14')]])
def test_complete_http_positive_controls(tmp_path, headers):
    with endpoint(headers) as url:
        report = verify_spec_data(spec({'id': 'http', 'type': 'http', 'url': url, 'status': 200,
                                     'json_field': 'ready', 'operator': 'eq', 'value': True}), root=tmp_path, allow_network=True)
    assert report.verdict is Verdict.VERIFIED


@pytest.mark.parametrize('kind', ['json', 'csv'])
@pytest.mark.parametrize('timestamp', ['missing', 'invalid', 'future', 'null'])
def test_metric_failure_remains_visible_when_freshness_is_unknown(tmp_path, kind, timestamp):
    ts = {'invalid': 'not-a-timestamp', 'future': '2099-01-01T00:00:00Z', 'null': None}.get(timestamp)
    path = tmp_path/('state.'+kind)
    source = {'type': kind, 'path': path.name, 'max_age_seconds': 5}
    if kind == 'json':
        raw = {'value': 100}
        if timestamp != 'missing': raw['ts'] = ts
        path.write_text(json.dumps(raw), encoding='utf-8')
        source.update(field='value', timestamp_field='ts')
    else:
        path.write_text('value\n100\n' if timestamp == 'missing' else 'value,ts\n100,'+(ts or '')+'\n', encoding='utf-8')
        source.update(column='value', timestamp_column='ts')
    report = verify_spec_data(spec({'id': 'm', 'type': 'metric', 'source': source, 'operator': 'lte', 'value': 5}), root=tmp_path)
    assert report.verdict is Verdict.NOT_VERIFIED, 'known threshold failure must not be hidden by unavailable freshness'
    assert report.results[0].error is not None


@pytest.mark.parametrize('value,stamp,expected', [
    (1, 'missing', Verdict.UNCERTAIN), (1, 'invalid', Verdict.UNCERTAIN),
    (1, 'fresh', Verdict.VERIFIED), (100, 'fresh', Verdict.NOT_VERIFIED),
    (1, 'stale', Verdict.NOT_VERIFIED), (100, 'stale', Verdict.NOT_VERIFIED),
])
def test_metric_conjunction_controls(tmp_path, value, stamp, expected):
    raw = {'value': value}
    if stamp != 'missing':
        raw['ts'] = 'bad' if stamp == 'invalid' else (datetime.now(timezone.utc)-timedelta(seconds=100 if stamp == 'stale' else 0)).isoformat()
    (tmp_path/'s.json').write_text(json.dumps(raw), encoding='utf-8')
    source = {'type': 'json', 'path': 's.json', 'field': 'value', 'timestamp_field': 'ts', 'max_age_seconds': 5}
    assert verify_spec_data(spec({'id': 'm', 'type': 'metric', 'source': source, 'operator': 'lte', 'value': 5}),root=tmp_path).verdict is expected


def base_report(tmp_path):
    return verify_spec_data(spec({'id': 'f', 'type': 'file', 'path': 'absent', 'exists': False}),root=tmp_path)


def save_rehashed(path, data):
    data = deepcopy(data)
    data['report_sha256'] = hashlib.sha256(canonical_json(data).encode()).hexdigest()
    path.write_text(json.dumps(data),encoding='utf-8')


@pytest.mark.parametrize('error', ['evidence could not be read', 'verification command cleanup was not confirmed'])
def test_report_pass_cannot_have_an_unresolved_error(tmp_path, error):
    raw = base_report(tmp_path).to_dict()
    raw['results'][0]['error'] = error
    path = tmp_path/'report.json'; save_rehashed(path, raw)
    assert not verify_json_report(path)


@pytest.mark.parametrize('field,value', [('required_passed', True), ('attempts', 1.0), ('duration_ms', -1), ('finished_at', '2000-01-01T00:00:00Z')])
def test_rehashed_invalid_metadata_is_rejected(tmp_path, field, value):
    raw = base_report(tmp_path).to_dict(); raw[field] = value
    path = tmp_path/'report.json';save_rehashed(path,raw)
    assert not verify_json_report(path)


def test_consistent_legacy_report_remains_readable(tmp_path):
    raw = base_report(tmp_path).to_dict(); raw.pop('specification_sha256')
    path=tmp_path/'report.json';save_rehashed(path,raw)
    assert verify_json_report(path)


def test_shortened_regular_file_read_is_inconclusive(tmp_path, monkeypatch):
    path=tmp_path/'s.json';path.write_bytes(b'{"value":1}TRAILING_INVALID_DATA')
    original=os.fdopen
    class ShortRead:
        def __init__(self, handle): self.handle=handle
        def __enter__(self): self.handle.__enter__(); return self
        def __exit__(self,*args): return self.handle.__exit__(*args)
        def fileno(self): return self.handle.fileno()
        def read(self,*args): return self.handle.read(11)
    monkeypatch.setattr(os,'fdopen',lambda *a,**k: ShortRead(original(*a,**k)))
    with pytest.raises(ValueError): read_regular_bytes(path,1024)


@pytest.mark.parametrize('failure', ['permission', 'io'])
def test_local_read_error_does_not_prove_absence(tmp_path, monkeypatch, failure):
    import worldstate_check.observations as module
    def error(*args): raise PermissionError('synthetic') if failure=='permission' else OSError('synthetic')
    monkeypatch.setattr(module,'stat_regular_path',error)
    assert base_report(tmp_path).verdict is Verdict.UNCERTAIN


@pytest.mark.parametrize('value,expected,tolerance', [(2**53+1,2**53,0),(10**400,10**400-1,1),(1e308,-1e308,1.7e308),(0.1+0.2,0.3,1e-15),(5e-324,0.,0.)])
def test_independent_integer_ratio_tolerance_oracle(value,expected,tolerance):
    def ratio(x): return (x,1) if type(x) is int else x.as_integer_ratio()
    vn,vd=ratio(value);en,ed=ratio(expected);tn,td=ratio(tolerance)
    oracle=abs(vn*ed-en*vd)*td <= tn*vd*ed
    assert compare_value(value,'eq',{'value':expected,'tolerance':tolerance})[0] == oracle
    assert compare_value(value,'ne',{'value':expected,'tolerance':tolerance})[0] != oracle


def test_snapshot_aliases_share_exact_bytes(tmp_path,monkeypatch):
    import worldstate_check.engine as engine
    root=tmp_path/'root';root.mkdir();data=root/'state.json';data.write_text('{"v":1}')
    alias=root/'alias.json'
    try: alias.symlink_to(data)
    except OSError: pytest.skip('symlinks unavailable')
    original=engine.CHECK_RUNNERS['json']
    def update(check,ctx):
        result=original(check,ctx);data.write_text('{"v":2}');return result
    monkeypatch.setitem(engine.CHECK_RUNNERS,'json',update)
    report=verify_spec_data(spec(*[{'id':str(i),'type':'json','path':p,'field':'v','operator':'eq','value':1} for i,p in enumerate(('state.json','alias.json'))]),root=root)
    assert report.verdict is Verdict.VERIFIED
    assert report.results[0].evidence['source_sha256']==report.results[1].evidence['source_sha256']


def test_valid_report_and_changed_checksum_control(tmp_path):
    path=write_json_report(base_report(tmp_path),tmp_path/'report.json')
    assert verify_json_report(path)
    raw=json.loads(path.read_text());raw['task']='different';path.write_text(json.dumps(raw))
    assert not verify_json_report(path)


@pytest.mark.parametrize('kind',['json','csv'])
def test_stale_evidence_fails_even_when_metric_value_is_missing(tmp_path,kind):
    path=tmp_path/('missing-value.'+kind)
    if kind=='json':
        path.write_text('{"ts":"2000-01-01T00:00:00Z"}')
        source={'type':kind,'path':path.name,'field':'missing','timestamp_field':'ts','max_age_seconds':5}
    else:
        path.write_text('ts\n2000-01-01T00:00:00Z\n')
        source={'type':kind,'path':path.name,'column':'missing','timestamp_column':'ts','max_age_seconds':5}
    report=verify_spec_data(spec({'id':'m','type':'metric','source':source,'operator':'eq','value':1}),root=tmp_path)
    assert report.verdict is Verdict.NOT_VERIFIED
    assert 'stale' in report.results[0].summary and report.results[0].error


@pytest.mark.parametrize('status',[204,304])
def test_http_no_body_status_is_not_confused_with_representation_length(tmp_path,status):
    with endpoint([('Content-Length','100')],body=b'',status=status) as url:
        report=verify_spec_data(spec({'id':'http','type':'http','url':url,'status':status}),root=tmp_path,allow_network=True)
    assert report.verdict is Verdict.VERIFIED


@pytest.mark.parametrize('length',['14, 14','00014'])
def test_valid_equivalent_content_lengths(tmp_path,length):
    with endpoint([('Content-Length',length)]) as url:
        report=verify_spec_data(spec({'id':'http','type':'http','url':url,'status':200}),root=tmp_path,allow_network=True)
    assert report.verdict is Verdict.VERIFIED


@pytest.mark.parametrize('chunked,expected',[
    (b'E\r\n{"ready":true}\r\n0\r\n\r\n',Verdict.VERIFIED),
    (b'E\r\n{"ready":true}\r\n',Verdict.NOT_VERIFIED),
])
def test_actual_http11_chunk_termination(tmp_path,chunked,expected):
    import socketserver
    class Response(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(2)
            request=b''
            while b'\r\n\r\n' not in request and len(request)<4096:
                piece=self.request.recv(1024)
                if not piece:return
                request+=piece
            self.request.sendall(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n'+chunked)
    with socketserver.TCPServer(('127.0.0.1',0),Response) as server:
        thread=Thread(target=server.handle_request,daemon=True);thread.start()
        url=f'http://127.0.0.1:{server.server_address[1]}/owned'
        report=verify_spec_data(spec({'id':'http','type':'http','url':url,'status':200,'json_field':'ready','operator':'eq','value':True}),root=tmp_path,allow_network=True)
        thread.join(timeout=3)
    assert report.verdict is expected


def test_framing_error_does_not_echo_sensitive_header_values(tmp_path):
    with endpoint([('Content-Length','SYNTHETIC_PRIVATE_HEADER')]) as url:
        report=verify_spec_data(spec({'id':'http','type':'http','url':url,'status':200}),root=tmp_path,allow_network=True)
    assert report.verdict is not Verdict.VERIFIED
    path=write_json_report(report,tmp_path/'redacted.json')
    assert 'SYNTHETIC_PRIVATE_HEADER' not in path.read_text()
