"""Synthetic audit checks. Only temporary files and mocked transports are used."""
import hashlib
import json
import socket
from copy import deepcopy

import pytest

from worldstate_check import SpecError, Verdict, verify_spec_data
from worldstate_check.cli import main
from worldstate_check.engine import derive_verdict
from worldstate_check.loader import validate_spec
from worldstate_check.report import verify_json_report
from worldstate_check.util import canonical_json


def spec(check=None):
    return {'version':1, 'task':'synthetic-audit', 'checks':[check or {'id':'x','type':'file','path':'missing','exists':False}]}


@pytest.mark.parametrize('flag', ['allow_network','allow_command','allow_outside_root'])
@pytest.mark.parametrize('value', ['false',1])
def test_safety_optins_require_actual_booleans(tmp_path, flag, value):
    with pytest.raises(ValueError): verify_spec_data(spec(), root=tmp_path, **{flag:value})


@pytest.mark.parametrize('damage', ['check-type','operator','source-type','deep'])
def test_invalid_schema_has_defined_specerror(damage):
    value=spec({'id':'j','type':'json','path':'state.json','field':'v','operator':'eq','value':1})
    if damage=='check-type':value['checks'][0]['type']=[]
    if damage=='operator':value['checks'][0]['operator']=[]
    if damage=='source-type':value['checks'][0]={'id':'m','type':'metric','source':{'type':[],'path':'x','field':'v'},'operator':'eq','value':1}
    if damage=='deep':
        nested=0
        for _ in range(1100):nested=[nested]
        value['checks'][0]['value']=nested
    with pytest.raises(SpecError): validate_spec(value)


def test_deep_json_is_uncertain_not_python_exception(tmp_path):
    (tmp_path/'state.json').write_text('{"v":1,"nested":'+'['*1100+'0'+']'*1100+'}')
    report=verify_spec_data(spec({'id':'j','type':'json','path':'state.json','field':'v','operator':'eq','value':1}), root=tmp_path)
    assert report.verdict is Verdict.UNCERTAIN


@pytest.mark.parametrize('failure', [socket.gaierror('synthetic DNS error'),TimeoutError('synthetic timeout'),PermissionError('synthetic local policy')])
def test_unobserved_tcp_unreachability_cannot_pass(tmp_path, monkeypatch, failure):
    def fail(*a,**k):raise failure
    monkeypatch.setattr(socket,'create_connection',fail)
    report=verify_spec_data(spec({'id':'t','type':'tcp','host':'synthetic.invalid','port':1234,'reachable':False}),root=tmp_path,allow_network=True)
    assert report.verdict is Verdict.UNCERTAIN


def test_multiple_checks_cannot_combine_incompatible_file_versions(tmp_path, monkeypatch):
    import worldstate_check.engine as engine
    path=tmp_path/'state.json';path.write_text('{"v":0}')
    original=engine.CHECK_RUNNERS['json']; calls=[]
    def changing(check,ctx):
        result=original(check,ctx)
        if not calls:path.write_text('{"v":1}')
        calls.append(True)
        return result
    monkeypatch.setitem(engine.CHECK_RUNNERS,'json',changing)
    value=spec({'id':'first','type':'json','path':'state.json','field':'v','operator':'eq','value':0})
    value['checks'].append({**value['checks'][0],'id':'second','value':1})
    report=verify_spec_data(value,root=tmp_path)
    assert report.verdict is not Verdict.VERIFIED


def test_memory_spec_mutation_cannot_change_inflight_target(tmp_path,monkeypatch):
    import worldstate_check.engine as engine
    (tmp_path/'state.json').write_text('{"v":0}')
    value=spec({'id':'first','type':'json','path':'state.json','field':'v','operator':'eq','value':0})
    value['checks'].append({**value['checks'][0],'id':'second','value':1})
    original=engine.CHECK_RUNNERS['json']
    def mutate(check,ctx):
        result=original(check,ctx);value['checks'][1]['value']=0;return result
    monkeypatch.setitem(engine.CHECK_RUNNERS,'json',mutate)
    assert verify_spec_data(value,root=tmp_path).verdict is Verdict.NOT_VERIFIED


@pytest.mark.parametrize('kind', ['spec','evidence'])
def test_cli_report_cannot_destroy_input(tmp_path,kind):
    source=tmp_path/'state.json';source.write_text('{"v":1}')
    specification=tmp_path/'spec.yaml';specification.write_text(json.dumps(spec({'id':'j','type':'json','path':'state.json','field':'v','operator':'eq','value':1})))
    target=source if kind=='evidence' else specification
    before=target.read_bytes()
    assert main(['verify',str(specification),'--report',str(target)])==2
    assert target.read_bytes()==before


@pytest.mark.parametrize('damage',['missing-schema','verdict','counts','duplicate-id','required-type'])
def test_rehashed_invalid_report_is_rejected(tmp_path,damage):
    report=verify_spec_data(spec(),root=tmp_path)
    data=report.to_dict()
    if damage=='missing-schema':data={'arbitrary':'not a report'}
    if damage=='verdict':data['verdict']='NOT_VERIFIED'
    if damage=='counts':data['required_passed']=77
    if damage=='duplicate-id':data['results'].append(deepcopy(data['results'][0]))
    if damage=='required-type':data['results'][0]['required']='false'
    data['report_sha256']=hashlib.sha256(canonical_json(data).encode()).hexdigest()
    path=tmp_path/'report.json';path.write_text(json.dumps(data))
    assert not verify_json_report(path)


def test_file_failure_is_not_hidden_by_unreadable_content(tmp_path):
    (tmp_path/'f').write_bytes(b'\xff')
    report=verify_spec_data(spec({'id':'f','type':'file','path':'f','exists':False,'contains':'READY'}),root=tmp_path)
    assert report.verdict is Verdict.NOT_VERIFIED


def test_hash_respects_explicit_read_budget(tmp_path):
    raw=b'x'*4096;(tmp_path/'f').write_bytes(raw)
    report=verify_spec_data(spec({'id':'f','type':'file','path':'f','sha256':hashlib.sha256(raw).hexdigest(),'max_read_bytes':8}),root=tmp_path)
    assert report.verdict is Verdict.UNCERTAIN


def test_empty_verdict_cannot_claim_verified():
    assert derive_verdict([]) is Verdict.UNCERTAIN


def test_csv_malformed_row_is_not_silently_discarded(tmp_path):
    (tmp_path/'v.csv').write_text('value,source\n9\n1,complete\n')
    check={'id':'m','type':'metric','source':{'type':'csv','path':'v.csv','column':'value'},'operator':'eq','value':1}
    assert verify_spec_data(spec(check),root=tmp_path).verdict is Verdict.UNCERTAIN
