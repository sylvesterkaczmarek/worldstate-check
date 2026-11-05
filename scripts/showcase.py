"""Reproduce software, spacecraft and maintenance outcomes using synthetic files."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from worldstate_check import verify_spec_data
from worldstate_check.report import write_json_report, verify_json_report
from worldstate_check.util import canonical_json


def demonstrate(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    rows=[]
    def run(name,data,checks,expected):
        directory=out/name;directory.mkdir()
        (directory/'state.json').write_text(data if isinstance(data,str) else json.dumps(data),encoding='utf-8')
        specification={'version':1,'task':name,'checks':checks}
        (directory/'specification.json').write_text(json.dumps(specification,indent=2)+'\n',encoding='utf-8')
        report=verify_spec_data(specification,root=directory)
        write_json_report(report,directory/'report.json')
        assert report.verdict.value==expected,(name,report.verdict.value,expected)
        assert verify_json_report(directory/'report.json')
        rows.append({'case':name,'verdict':report.verdict.value,'expected':expected,'passed':True})
        return report
    def state(identifier,field,value,op='eq'):
        return {'id':identifier,'type':'json','path':'state.json','field':field,'operator':op,'value':value}
    deploy=[state('agent-ack','claimed_complete',True),state('service-health','health.status',200)]
    run('deployment_ack_without_health',{'claimed_complete':True,'health':{'status':503}},deploy,'NOT_VERIFIED')
    run('deployment_recovered',{'claimed_complete':True,'health':{'status':200}},deploy,'VERIFIED')
    spacecraft=[state('ack','command_acknowledged',True),state('payload-off','payload_power','off'),state('attitude','attitude_error_deg',3.,'lte')]
    run('spacecraft_ack_without_safe_state',{'command_acknowledged':True,'payload_power':'off','attitude_error_deg':9.},spacecraft,'NOT_VERIFIED')
    metric={'id':'temperature','type':'metric','source':{'type':'json','path':'state.json','field':'temperature','timestamp_field':'observed_at','max_age_seconds':5},'operator':'lte','value':75}
    now=datetime.now(timezone.utc)
    run('maintenance_fresh',{'temperature':62,'observed_at':now.isoformat()},[metric],'VERIFIED')
    run('maintenance_stale',{'temperature':62,'observed_at':(now-timedelta(seconds=60)).isoformat()},[metric],'NOT_VERIFIED')
    run('maintenance_timestamp_missing',{'temperature':62},[metric],'UNCERTAIN')
    run('ambiguous_observation','{"ready":false,"ready":true}',[state('ready','ready',True)],'UNCERTAIN')
    saved=json.loads((out/'deployment_ack_without_health'/'report.json').read_text())
    saved.pop('report_sha256');saved['verdict']='VERIFIED'
    saved['report_sha256']=hashlib.sha256(canonical_json(saved).encode()).hexdigest()
    mutated=out/'inconsistent-rehashed-report.json';mutated.write_text(json.dumps(saved),encoding='utf-8')
    assert not verify_json_report(mutated)
    rows.append({'case':'rehashed_inconsistent_verdict','verdict':'INVALID_REPORT','expected':'INVALID_REPORT','passed':True})
    summary={'passed':len(rows),'total':len(rows),'cases':rows,
             'scope':'Synthetic local observations only. No real deployment, robot, spacecraft, model inference, external service, or command execution. Checksums establish consistency, not source authenticity.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    for row in rows:print(f'{row["case"]:38} {row["verdict"]:15} PASS')
    print(summary['scope'])
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    demonstrate(args.out)
