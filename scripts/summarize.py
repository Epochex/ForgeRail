"""Summarize existing execution evidence without upgrading unexecuted checks."""
import collections
import datetime
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]


def read(name):
    p=ROOT/name
    return json.loads(p.read_text(encoding='utf-8-sig')) if p.is_file() else {}


def summarize():
    cases=[]
    junit=ROOT/'reports/pytest.xml'
    if junit.exists(): cases=list(ET.parse(junit).iter('testcase'))
    def proof(*names):
        found=[x for x in cases if any(x.attrib['name'].startswith(name) for name in names)]
        return bool(found) and all(not list(x) or all(y.tag not in ('failure','error','skipped') for y in x) for x in found) and all(any(x.attrib['name'].startswith(n) for x in found) for n in names)
    def status(value): return 'passed' if value else 'blocked'
    engine=read('reports/unity/engine-status.json')
    demo=read('reports/demo.json'); jenkins=read('reports/labs/jenkins.json')
    runtime=read('reports/labs/runtime.json'); messaging=read('reports/labs/messaging.json')
    images=read('reports/labs/images.json'); services=read('reports/labs/services.json')
    def engine_pass(name): return engine.get(name,{}).get('status')=='passed'
    player=engine_pass('player_build') and engine_pass('player_smoke')
    parallel=read('reports/unity/parallel.json'); runs=parallel.get('runs',[])
    parallel_pass=(parallel.get('status')=='passed' and parallel.get('overlap_seconds',0)>0 and len(runs)==2
                   and all(r.get('status')=='passed' and r.get('exit_code')==0 for r in runs)
                   and all(len({r.get(k) for r in runs})==2 for k in ('commit_sha','worktree','library','output_dir','build_id')))
    rows=[]
    def row(id,name,passed,evidence,detail=''):
        rows.append({'id':id,'name':name,'status':status(passed),'evidence':evidence,'detail':detail})
    row('A01','Unity Player build and smoke',player,['reports/unity/engine-status.json'],'Requires actual Editor and Player execution')
    row('A02','Filesystem resource admission',proof('test_missing_file_and_directory_metadata_block_build','test_duplicate_and_invalid_guids_are_reported','test_case_conflict_is_portably_detected_from_orphan_meta'),['reports/pytest.xml'])
    row('A03','Unity semantic resource checks',engine_pass('editor_checks'),['reports/unity/engine-status.json'])
    row('A04','Parallel Unity branch workspaces',parallel_pass,['reports/unity/parallel.json'],'Requires actual two-branch Unity execution overlap and isolated workspaces')
    row('A05','Idempotency and conflicting immutable input',proof('test_idempotency_survives_restart_and_conflicting_input_is_rejected'),['reports/pytest.xml'])
    row('A06','Tampered artifact and manifest rejection',proof('test_package_roundtrip_and_tampering','test_manifest_file_hash_must_match_payload') and demo.get('artifact_tamper_rejected') is True,['reports/pytest.xml','reports/demo.json'])
    row('A07','Resource caches and engine export invalidation',engine_pass('export_cache') and proof('test_resource_changes_invalidate_cache_and_same_input_hits','test_cache_corruption_becomes_miss_without_partial_destination'),['reports/pytest.xml','reports/unity/engine-status.json'],'Filesystem cache and executable C# cache contracts are distinct from actual engine cache measurements')
    row('A08','Bounded lease recovery',proof('test_attempts_are_bounded_and_cancelled_owner_cannot_report','test_expired_worker_cannot_report_or_renew_and_fresh_attempt_differs'),['reports/pytest.xml'])
    row('A09','Stale result rejection',proof('test_cancelled_and_expired_artifact_uploads_cannot_commit') and demo.get('stale_report_rejected') is True,['reports/pytest.xml','reports/demo.json'])
    row('A10','In-flight cancellation and descendant cleanup',proof('test_live_cancellation_stops_running_node_and_never_publishes','test_entire_process_tree_stops_producing_heartbeat'),['reports/pytest.xml'])
    row('A11','Partial publication recovery after restart',proof('test_database_failure_after_blob_admission_can_retry_without_partial_success') and read('reports/labs/controlplane.json').get('status')=='passed',['reports/pytest.xml','reports/labs/controlplane.json'])
    row('A12','Test-channel promotion and rollback',proof('test_release_windows_and_rollback_restore_previous_pointer') and read('reports/release-validation.json').get('status')=='passed',['reports/pytest.xml','reports/release-validation.json'],'Two artifacts, eight fresh Player observations and authoritative channel rollback; local test channels')
    row('A13','Real Jenkins agent pipeline',jenkins.get('status')=='passed' and jenkins.get('result')=='SUCCESS' and read('reports/labs/jenkins-unity-verification.json').get('status')=='passed',['reports/labs/jenkins.json','reports/labs/jenkins-source.json','reports/labs/jenkins-unity-verification.json'])
    row('A14','Core edge identity and offline load',runtime.get('status')=='passed',['reports/labs/runtime.json'],'Docker executed; k3s and systemd status retained in raw report')
    row('A15','Redpanda crash replay and shadow isolation',messaging.get('status')=='passed',['reports/labs/messaging.json'])
    row('A16','Eight target builds and startup',images.get('status')=='passed' and services.get('status')=='passed',['reports/labs/images.json','reports/labs/services.json'])
    row('A17','Layered network diagnostics',proof('test_network_refusal_reports_tcp_after_dns_success','test_network_http_success_status_error_and_response_timeout','test_network_probe_deadline_bounds_slow_trickling_http_headers'),['reports/pytest.xml'])
    failures=sum(any(y.tag in ('failure','error') for y in x) for x in cases)
    skips=sum(any(y.tag=='skipped' for y in x) for x in cases)
    result={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'source_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'overall':'failed' if failures else ('partial' if any(r['status']!='passed' for r in rows) else 'passed'),
            'python_tests':{'passed':len(cases)-failures-skips,'failed':failures,'skipped':skips},
            'counts':dict(collections.Counter(r['status'] for r in rows)),
            'scope':'Personal engineering lab. Historical business metrics are not measured here.',
            'acceptance':rows}
    (ROOT/'reports/acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('overall','python_tests','counts')},ensure_ascii=False))
    return result


if __name__=='__main__': summarize()
