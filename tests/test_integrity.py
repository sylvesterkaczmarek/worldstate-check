"""Positive/negative controls for observations, input safety and report semantics."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time

import pytest

from worldstate_check import SpecError, Verdict, verify_spec_data
from worldstate_check.cli import main
from worldstate_check.loader import load_spec
from worldstate_check.models import CheckStatus
from worldstate_check.processes import run_bounded
from worldstate_check.report import verify_json_report, write_json_report, render_text
from worldstate_check.safe_io import read_regular_bytes
from worldstate_check.util import strict_json_loads


def spec(check=None):
    return {'version':1,'task':'integrity-control','checks':[check or {'id':'f','type':'file','path':'missing','exists':False}]}


def state_check(**extra):
    return {'id':'j','type':'json','path':'state.json','field':'v','operator':'eq','value':1,**extra}


@pytest.mark.parametrize('value',[True,1,'false',float('nan'),None])
def test_timing_invalid_values_fail_cleanly(tmp_path,value):
    if value == 1 and type(value) is int: value=10**400
    with pytest.raises(ValueError): verify_spec_data(spec(),root=tmp_path,wait_seconds=value)


@pytest.mark.parametrize('raw',['{"v":"\\ud800"}','{"v":1,"v":2}','{"v":1e999}','{"v":NaN}'])
def test_strict_json_invalid_evidence(raw):
    with pytest.raises(ValueError): strict_json_loads(raw)


@pytest.mark.parametrize('value',[[],{},[1,True,None],{'unicode':'é'}])
def test_strict_json_positive_controls(value):
    assert strict_json_loads(json.dumps(value))==value


@pytest.mark.parametrize('body',['version: 1\nversion: 1\n','value: &a [*a]\n','value: '+ '['*1100+'0'+']'*1100])
def test_ambiguous_or_recursive_yaml_has_specerror(tmp_path,body):
    p=tmp_path/'bad.yaml';p.write_text(body)
    with pytest.raises(SpecError):load_spec(p)


def test_whole_input_is_checked_before_any_observation(tmp_path,monkeypatch):
    import worldstate_check.engine as engine
    value=spec();value['checks'].append({'id':'bad','type':[]})
    monkeypatch.setitem(engine.CHECK_RUNNERS,'file',lambda *a:pytest.fail('invalid specification touched evidence'))
    with pytest.raises(SpecError):verify_spec_data(value,root=tmp_path)


def test_required_failure_has_precedence_over_missing_evidence(tmp_path):
    (tmp_path/'state.json').write_text('{bad-json')
    value=spec(state_check());value['checks'].append({'id':'missing','type':'file','path':'absent','exists':True})
    report=verify_spec_data(value,root=tmp_path)
    assert report.verdict is Verdict.NOT_VERIFIED
    assert [r.status for r in report.results]==[CheckStatus.UNKNOWN,CheckStatus.FAIL]


def test_optional_unknown_does_not_block_real_required_pass(tmp_path):
    value=spec();value['checks'].append({'id':'http','type':'http','url':'http://127.0.0.1:1','status':200,'required':False})
    assert verify_spec_data(value,root=tmp_path).verdict is Verdict.VERIFIED


def test_report_fingerprint_is_stable_and_binds_exact_specification(tmp_path):
    first=verify_spec_data(spec(),root=tmp_path)
    again=verify_spec_data(spec(),root=tmp_path)
    other=spec();other['checks'][0]['exists']=True
    assert first.specification_sha256==again.specification_sha256
    assert first.specification_sha256!=verify_spec_data(other,root=tmp_path).specification_sha256


def test_one_shared_snapshot_for_file_json_and_metric(tmp_path,monkeypatch):
    import worldstate_check.engine as engine
    p=tmp_path/'state.json';p.write_text('{"v":1}')
    first={'id':'file','type':'file','path':'state.json','contains':'1'}
    value=spec(first);value['checks'] += [state_check(),{'id':'metric','type':'metric','source':{'type':'json','path':'state.json','field':'v'},'operator':'eq','value':1}]
    original=engine.CHECK_RUNNERS['file']
    def mutate(check,ctx):
        result=original(check,ctx);p.write_text('{"v":2}');return result
    monkeypatch.setitem(engine.CHECK_RUNNERS,'file',mutate)
    report=verify_spec_data(value,root=tmp_path)
    assert report.verdict is Verdict.VERIFIED
    assert len({r.evidence['source_sha256'] for r in report.results})==1
    assert report.results[1].observed==report.results[2].observed==1


def test_retries_refresh_all_file_snapshots(tmp_path,monkeypatch):
    import worldstate_check.engine as engine
    p=tmp_path/'state.json';p.write_text('{"v":0}')
    original=engine.CHECK_RUNNERS['json']
    def mutate(check,ctx):
        result=original(check,ctx);p.write_text('{"v":1}');return result
    monkeypatch.setitem(engine.CHECK_RUNNERS,'json',mutate)
    report=verify_spec_data(spec(state_check()),root=tmp_path,wait_seconds=.2,poll_interval=.01)
    assert report.verdict is Verdict.VERIFIED and report.attempts==2


def test_per_check_read_limit_applies_to_shared_large_snapshot(tmp_path):
    (tmp_path/'state.json').write_text('{"v":1,"padding":"long padding"}')
    value=spec(state_check(max_read_bytes=1024));value['checks'].append(state_check(id='small',max_read_bytes=2))
    report=verify_spec_data(value,root=tmp_path)
    assert report.results[0].status is CheckStatus.PASS and report.results[1].status is CheckStatus.UNKNOWN
    assert report.verdict is Verdict.UNCERTAIN


@pytest.mark.parametrize('kind',['file','json','metric'])
def test_oversized_evidence_is_unknown_for_every_reader(tmp_path,kind):
    (tmp_path/'state.json').write_text('{"v":1,"padding":"'+ 'x'*128+'"}')
    check=state_check(max_read_bytes=8)
    if kind=='file':check={'id':'f','type':'file','path':'state.json','contains':'v','max_read_bytes':8}
    if kind=='metric':check={'id':'m','type':'metric','source':{'type':'json','path':'state.json','field':'v','max_read_bytes':8},'operator':'eq','value':1}
    assert verify_spec_data(spec(check),root=tmp_path).verdict is Verdict.UNCERTAIN


def test_source_hash_identifies_observed_bytes(tmp_path):
    raw=b'{"v":1}';(tmp_path/'state.json').write_bytes(raw)
    report=verify_spec_data(spec(state_check()),root=tmp_path)
    evidence=report.results[0].evidence
    assert evidence['source_sha256']==hashlib.sha256(raw).hexdigest()
    assert evidence['size_bytes']==len(raw) and evidence['observed_at'].endswith('Z')


@pytest.mark.parametrize('kind',['hardlink','symlink-outside'])
def test_nonlocal_or_aliased_content_is_not_read(tmp_path,kind):
    root=tmp_path/'root';root.mkdir();source=tmp_path/'outside.json';source.write_text('{"v":1}')
    path=root/'state.json'
    try:
        if kind=='hardlink':os.link(source,path)
        else:path.symlink_to(source)
    except OSError:pytest.skip('links unavailable')
    assert verify_spec_data(spec(state_check()),root=root).verdict is Verdict.UNCERTAIN


@pytest.mark.skipif(not hasattr(os,'mkfifo'),reason='POSIX special file')
def test_fifo_is_rejected_without_waiting_for_writer(tmp_path):
    path=tmp_path/'state.json';os.mkfifo(path)
    before=time.monotonic()
    assert verify_spec_data(spec(state_check()),root=tmp_path).verdict is Verdict.UNCERTAIN
    assert time.monotonic()-before<2


@pytest.mark.skipif(os.name!='posix',reason='POSIX descriptor-relative operation')
def test_parent_redirect_race_never_reads_replacement(tmp_path,monkeypatch):
    owned=tmp_path/'owned';owned.mkdir();(owned/'data').write_text('safe')
    other=tmp_path/'other';other.mkdir();(other/'data').write_text('outside')
    original=os.open; switched=[]
    def replace_parent(path,flags,*args,**kwargs):
        if path=='data' and kwargs.get('dir_fd') is not None and not switched:
            owned.rename(tmp_path/'retained');owned.symlink_to(other,target_is_directory=True);switched.append(True)
        return original(path,flags,*args,**kwargs)
    monkeypatch.setattr(os,'open',replace_parent)
    monkeypatch.setattr(os,'supports_dir_fd',{*os.supports_dir_fd,replace_parent})
    raw,_=read_regular_bytes(owned/'data',32)
    assert switched and raw==b'safe'


@pytest.mark.parametrize('offset,verdict',[(-10,Verdict.NOT_VERIFIED),(20,Verdict.UNCERTAIN),(0,Verdict.VERIFIED)])
def test_freshness_uses_explicit_timestamp(tmp_path,offset,verdict):
    stamp=(datetime.now(timezone.utc)+timedelta(seconds=offset)).isoformat()
    (tmp_path/'state.json').write_text(json.dumps({'v':1,'observed_at':stamp}))
    check={'id':'m','type':'metric','source':{'type':'json','path':'state.json','field':'v','timestamp_field':'observed_at','max_age_seconds':5},'operator':'eq','value':1}
    assert verify_spec_data(spec(check),root=tmp_path).verdict is verdict


@pytest.mark.parametrize('alias',['same','hardlink','symlink'])
def test_output_collision_rejected_before_running_checks(tmp_path,monkeypatch,alias):
    import worldstate_check.cli as cli
    source=tmp_path/'s.yaml';source.write_text(json.dumps(spec()))
    target=source if alias=='same' else tmp_path/'out.json'
    try:
        if alias=='hardlink':os.link(source,target)
        if alias=='symlink':target.symlink_to(source)
    except OSError:pytest.skip('links unavailable')
    monkeypatch.setattr(cli,'verify_spec_data',lambda *a,**k:pytest.fail('unsafe output was not preflighted'))
    assert main(['verify',str(source),'--report',str(target)])==2
    assert source.read_text()==json.dumps(spec())


def test_failed_report_replace_preserves_existing_output(tmp_path,monkeypatch):
    report=verify_spec_data(spec(),root=tmp_path)
    target=tmp_path/'report.json';target.write_text('previous')
    def fail(*a):raise OSError('synthetic disk error')
    monkeypatch.setattr(os,'replace',fail)
    with pytest.raises(OSError):write_json_report(report,target)
    assert target.read_text()=='previous'
    assert list(tmp_path.glob('.report.json.*'))==[]


def test_terminal_output_cannot_insert_forged_verdict(tmp_path,monkeypatch):
    from dataclasses import replace
    report=verify_spec_data(spec(),root=tmp_path)
    check=replace(report.results[0],summary='bad\nVERDICT: VERIFIED\x1b[2J')
    report=replace(report,results=[check])
    text=render_text(report)
    assert '\x1b' not in text and 'bad\nVERDICT' not in text
    assert 'bad\\nVERDICT' in text


@pytest.mark.parametrize('field',['schema_version','attempts','required_total'])
def test_boolean_report_counts_rejected(tmp_path,field):
    report=verify_spec_data(spec(),root=tmp_path)
    data=report.to_dict();data[field]=True
    from worldstate_check.util import canonical_json
    data['report_sha256']=hashlib.sha256(canonical_json(data).encode()).hexdigest()
    p=tmp_path/'report.json';p.write_text(json.dumps(data))
    assert not verify_json_report(p)


def test_report_checksum_is_not_authentication(tmp_path):
    report=verify_spec_data(spec(),root=tmp_path)
    data=report.to_dict();data['task']='different-valid-task'
    from worldstate_check.util import canonical_json
    data['report_sha256']=hashlib.sha256(canonical_json(data).encode()).hexdigest()
    p=tmp_path/'report.json';p.write_text(json.dumps(data))
    assert verify_json_report(p), 'consistency cannot authenticate an unkeyed checksum'


def test_command_standard_input_is_closed(tmp_path):
    result=run_bounded([sys.executable,'-I','-S','-c','import sys;print(repr(sys.stdin.read()))'],cwd=tmp_path,env=os.environ.copy(),timeout=2,max_bytes=100)
    assert result.returncode==0 and result.stdout.strip()==b"''"


@pytest.mark.parametrize('channel',[1,2])
def test_large_output_is_stopped_without_waiting_for_timeout(tmp_path,channel):
    before=time.monotonic()
    result=run_bounded([sys.executable,'-I','-S','-c',f'import os,time;os.write({channel},b"x"*200000);time.sleep(10)'],cwd=tmp_path,env=os.environ.copy(),timeout=8,max_bytes=1024)
    assert result.output_limited and not result.timed_out
    assert len(result.stdout)<=1024 and len(result.stderr)<=1024
    assert time.monotonic()-before<5


@pytest.mark.skipif(os.name!='posix',reason='POSIX process groups')
@pytest.mark.parametrize('mode',['normal','timeout'])
def test_owned_descendants_are_stopped(tmp_path,mode):
    marker=tmp_path/'late';ready=tmp_path/'ready'
    child=tmp_path/'child.py';child.write_text(f'from pathlib import Path\nimport time\nPath({str(ready)!r}).touch()\ntime.sleep(1)\nPath({str(marker)!r}).touch()\n')
    script=f'import subprocess,sys,time\nfrom pathlib import Path\nsubprocess.Popen([sys.executable,"-I","-S",{str(child)!r}])\nwhile not Path({str(ready)!r}).exists():time.sleep(.01)\n'+('time.sleep(5)\n' if mode=='timeout' else '')
    result=run_bounded([sys.executable,'-I','-S','-c',script],cwd=tmp_path,env=os.environ.copy(),timeout=.3 if mode=='timeout' else 3,max_bytes=1024)
    assert ready.exists() and result.timed_out==(mode=='timeout')
    time.sleep(1.1);assert not marker.exists()


def test_explicit_connection_refusal_can_confirm_unreachability(tmp_path,monkeypatch):
    def fail(*a,**k):raise ConnectionRefusedError('synthetic refusal')
    monkeypatch.setattr(socket,'create_connection',fail)
    check={'id':'t','type':'tcp','host':'127.0.0.1','port':1234,'reachable':False}
    assert verify_spec_data(spec(check),root=tmp_path,allow_network=True).verdict is Verdict.VERIFIED


@pytest.mark.parametrize('extra',[{'min':2},{'max':2},{'values':[1]}])
def test_unused_comparison_parameters_cannot_silently_pass(tmp_path,extra):
    with pytest.raises(SpecError):verify_spec_data(spec(state_check(**extra)),root=tmp_path)


def test_http_comparison_requires_a_field(tmp_path):
    check={'id':'h','type':'http','url':'http://127.0.0.1:1','status':200,'operator':'eq','value':True}
    with pytest.raises(SpecError):verify_spec_data(spec(check),root=tmp_path)


@pytest.mark.parametrize('kind',['http','tcp'])
def test_unrepresentable_socket_timeout_has_a_defined_result(tmp_path,monkeypatch,kind):
    def fail(*a,**k):raise OverflowError('timeout exceeds native representation')
    if kind=='tcp':
        monkeypatch.setattr(socket,'create_connection',fail)
        check={'id':'n','type':'tcp','host':'127.0.0.1','port':1,'reachable':False,'timeout_seconds':1e308}
    else:
        import urllib.request
        monkeypatch.setattr(urllib.request,'urlopen',fail)
        check={'id':'n','type':'http','url':'http://127.0.0.1:1','status':200,'timeout_seconds':1e308}
    assert verify_spec_data(spec(check),root=tmp_path,allow_network=True).verdict is Verdict.UNCERTAIN


def test_showcase_runs_without_network_or_commands(tmp_path,monkeypatch):
    import runpy
    import worldstate_check.processes as processes
    monkeypatch.setattr(socket,'create_connection',lambda *a,**k:pytest.fail('showcase used network'))
    monkeypatch.setattr(processes,'run_bounded',lambda *a,**k:pytest.fail('showcase ran a command'))
    demo=runpy.run_path(str(Path(__file__).parents[1]/'scripts/showcase.py'))
    out=tmp_path/'showcase'
    assert demo['demonstrate'](out)['passed']==8
    with pytest.raises(FileExistsError):demo['demonstrate'](out)


def test_report_can_be_verified_through_user_selected_parent_alias(tmp_path):
    actual=tmp_path/'actual';actual.mkdir();alias=tmp_path/'alias'
    try:alias.symlink_to(actual,target_is_directory=True)
    except OSError:pytest.skip('directory aliases unavailable')
    report=verify_spec_data(spec(),root=actual)
    write_json_report(report,alias/'report.json')
    assert verify_json_report(alias/'report.json')


@pytest.mark.parametrize('key',['path','host','argv'])
def test_nul_path_and_command_inputs_rejected_before_evaluation(tmp_path,key):
    if key=='path':check=state_check(path='bad\0file')
    elif key=='host':check={'id':'t','type':'tcp','host':'bad\0host','port':1234}
    else:check={'id':'c','type':'command','argv':['bad\0executable'],'exit_code':0}
    with pytest.raises(SpecError):verify_spec_data(spec(check),root=tmp_path)


@pytest.mark.parametrize('age,verdict',[(5.0,Verdict.VERIFIED),(5.0004,Verdict.NOT_VERIFIED)])
def test_freshness_report_retains_actual_boundary_value(tmp_path,monkeypatch,age,verdict):
    monkeypatch.setattr('worldstate_check.checks.metric.freshness_age_seconds',lambda *a:age)
    (tmp_path/'state.json').write_text('{"v":1,"timestamp":"2026-11-05T00:00:00Z"}')
    check={'id':'m','type':'metric','source':{'type':'json','path':'state.json','field':'v','timestamp_field':'timestamp','max_age_seconds':5},'operator':'eq','value':1}
    report=verify_spec_data(spec(check),root=tmp_path)
    assert report.verdict is verdict and report.results[0].evidence['age_seconds']==age
    if verdict is Verdict.NOT_VERIFIED:assert report.results[0].observed['age_seconds']>5


@pytest.mark.parametrize('change',['none','path-ctime','descriptor-ctime'])
def test_native_stat_ctime_views_are_compared_within_their_api(tmp_path,monkeypatch,change):
    from types import SimpleNamespace
    import worldstate_check.safe_io as safe_io
    path=tmp_path/'data';path.write_bytes(b'synthetic')
    original_stat=safe_io._stat;original_fstat=os.fstat
    counts={'path':0,'descriptor':0}
    def fields(info,ctime):
        return SimpleNamespace(st_dev=info.st_dev,st_ino=info.st_ino,st_size=info.st_size,
                               st_mtime_ns=info.st_mtime_ns,st_ctime_ns=ctime,
                               st_nlink=info.st_nlink,st_mode=info.st_mode,
                               st_file_attributes=getattr(info,'st_file_attributes',0))
    def path_stat(*args):
        info=original_stat(*args);counts['path']+=1
        # Creation time versus change time can differ for an unchanged file.
        ctime=info.st_ctime_ns-123456789
        if change=='path-ctime' and counts['path']>1:ctime+=100
        return fields(info,ctime)
    def descriptor_stat(*args):
        info=original_fstat(*args);counts['descriptor']+=1
        ctime=info.st_ctime_ns
        if change=='descriptor-ctime' and counts['descriptor']>1:ctime+=100
        return fields(info,ctime)
    monkeypatch.setattr(safe_io,'_stat',path_stat)
    monkeypatch.setattr(os,'fstat',descriptor_stat)
    if change=='none':assert read_regular_bytes(path,32)[0]==b'synthetic'
    else:
        with pytest.raises(ValueError,match='changed during observation'):read_regular_bytes(path,32)


@pytest.mark.skipif(os.name!='posix',reason='POSIX group cleanup')
@pytest.mark.parametrize('remaining',['gone','permission','exists'])
def test_cleanup_permission_error_requires_group_absence_confirmation(monkeypatch,remaining):
    from worldstate_check.processes import _stop
    calls=[]
    class Process:
        pid=456789
        def poll(self):return 0
        def wait(self,timeout):calls.append(('wait',timeout));return 0
    def signal_group(pid,sig):
        calls.append((pid,sig))
        assert pid==456789
        if sig!=0:raise PermissionError('synthetic unreaped leader')
        if remaining=='gone':raise ProcessLookupError('group gone')
        if remaining=='permission':raise PermissionError('still not permitted')
    monkeypatch.setattr(os,'killpg',signal_group)
    error=_stop(Process())
    assert (error is None)==(remaining=='gone')
    assert calls[1]==('wait',5) and calls[-1]==(456789,0)


def test_unresolved_command_cleanup_is_not_verified(tmp_path,monkeypatch):
    from worldstate_check.processes import CommandOutcome
    result=CommandOutcome(0,b'OK',b'',2,0,False,False,'PermissionError')
    monkeypatch.setattr('worldstate_check.checks.command.run_bounded',lambda *a,**k:result)
    check={'id':'c','type':'command','argv':['synthetic'],'exit_code':0}
    report=verify_spec_data(spec(check),root=tmp_path,allow_command=True)
    assert report.verdict is Verdict.UNCERTAIN
    assert report.results[0].evidence['cleanup_error']=='PermissionError'
