"""Failure recognition is separate from aggregate success: wrong failures stay errors."""


def recognizes(case, variant, result):
    facts=result.get('facts',{})
    checks={c['label']:c['passed'] for c in result['checks']}
    failed=lambda label: checks.get(label) is False
    if case in ('01','02'):
        rule={'import':'texture_compression','naming':'asset_name','budget':'asset_too_large',
              'duplicate_guid':'duplicate_guid','missing_reference':'unresolved_reference','broken_prefab':'prefab_schema'}[variant]
        return rule in {i['rule_id'] for i in facts['issues']}
    if case=='03':
        return bool(facts['unmerged_index']) if variant=='text_conflict' else not facts['unmerged_index'] and failed('功能与热修回归通过')
    if case=='04':
        return any(p['exit_code']==23 for p in facts['processes']) if variant=='lock' else all(p['exit_code']==0 for p in facts['processes']) and facts['actual_shas']!=facts['expected_shas']
    if case=='05':
        if variant=='compile': return facts['compile']['exit_code']!=0 and 'SyntaxError' in facts['compile']['stdout']
        if variant=='test': return facts['compile']['exit_code']==0 and facts['test']['exit_code']!=0 and 'AssertionError' in facts['test']['stdout']
        return checks.get('源码编译通过') and checks.get('行为测试通过') and failed('Release 必需测试与运行门禁')
    if case=='06':
        error={'missing_asset':'FileNotFoundError','runtime_config':'unsupported runtime mode','crash':'fixture startup crash'}[variant]
        return (checks.get('源码编译通过') and checks.get('行为测试通过') and bool(facts.get('package'))
                and bool(facts.get('runtime')) and facts['runtime']['exit_code']!=0 and error in facts['runtime']['stdout'])
    if case=='07':
        return failed({'dependency':'依赖改变使 key 失效','corruption':'缓存无损坏条目','repeat':'重复输入实际命中缓存'}[variant])
    if case=='08': return failed('独立任务并行重叠' if variant=='serial' else '打包发生在导出后')
    if case=='09':
        reason={'capability':'capability_mismatch','busy':'all_slots_busy','lease':'lease_expired_without_backup'}[variant]
        return facts['queue_reason']==reason and failed('目标被合适节点认领并执行') and (variant!='lease' or facts['old_report']['status']==409)
    if case=='10':
        return (facts['process']['timed_out' if variant=='timeout' else 'cancelled']
                and set(facts['pids'])=={'parent','child'} and not any(facts['pids_alive_after_reap'].values())
                and facts['heartbeat_stopped'] and facts['late_report']['status']==409)
    if case=='11':
        return checks.get('本机 Git 与 Python 可执行') and checks.get('工作目录实际可写') and failed({'editor':'fixture Editor 精确版本匹配','sdk':'fixture SDK 描述满足要求','license_budget':'fixture 授权描述有效'}[variant])
    if case=='12': return facts['first_failed_layer']=={'dns':'DNS','tcp':'TCP','http':'HTTP'}[variant]
    if case=='13': return bool(facts['admission_error']) and facts['mutation']==variant and checks.get('源码编译通过') and checks.get('行为测试通过')
    if case=='14': return bool(facts['admission_error']) and bool(facts['baseline_artifact']) and bool(facts['candidate_artifact'])
    if case=='15': return failed('下载字节小于全量' if variant=='full' else '独立客户端加载更新资源')
    if case=='16': return any(r['status']=='BLOCKED' and r['missing'] for r in facts['targets'])
    raise ValueError('unregistered failure recognition')
