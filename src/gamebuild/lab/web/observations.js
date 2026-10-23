// Pure projection: missing measurements stay missing, including old exported runs.
const RULES = {
  texture_compression:'贴图压缩 · compression',texture_readable:'CPU 可读 · readable',
  asset_name:'资源命名',asset_too_large:'单资源体积预算',duplicate_guid:'GUID 唯一性',
  unresolved_reference:'资源引用存在',prefab_schema:'Prefab 描述可解析',
};
export function comparisonRows(before, after) {
  if (Array.isArray(before?.facts?.issues)) {
    const key=i=>`${i.rule_id}:${i.path}`;
    const prior=new Map(before.facts.issues.map(i=>[key(i),i]));
    const measured=Array.isArray(after?.facts?.issues);
    const later=new Map((after?.facts?.issues || []).map(i=>[key(i),i]));
    return [...new Set([...prior.keys(),...later.keys()])].map(k=>{
      const old=prior.get(k),now=later.get(k),issue=old || now;
      return {label:(RULES[issue.rule_id] || issue.rule_id) + (issue.unit === 'bytes' ? '（字节）' : ''),path:issue.path,
        expected:issue.expected ?? '规则满足',before:old ? old.actual ?? old.message ?? '规则未满足' : '未检出此违规',
        after:!after ? '尚未复验' : !measured ? '缺少复验观测，不能判断' : now ? now.actual ?? now.message ?? '仍有违规' : '扫描未再检出此违规',
        failed:!!old,fixed:measured && !now};
    });
  }
  const old=new Map((before?.checks || []).map(c=>[c.label,c]));
  const now=new Map((after?.checks || []).map(c=>[c.label,c]));
  const keys=[...new Set([...old.keys(),...now.keys()])].filter(k=>old.get(k)?.passed===false || now.get(k)?.passed===false);
  return keys.map(label=>({label,expected:(now.get(label) || old.get(label)).expected,
    before:old.get(label)?.actual ?? '缺少故障阶段观测',
    after:now.has(label) ? now.get(label).actual : after ? '缺少复验观测，不能判断' : '尚未复验',
    failed:old.get(label)?.passed===false,fixed:now.get(label)?.passed===true}));
}

export function outcomeTitle(before,after,verified,repaired) {
  const issues=before?.facts?.issues;
  if (verified && Array.isArray(issues)) {
    return Array.isArray(after?.facts?.issues)
      ? `${issues.length} 项违规 → ${after.facts.issues.length} 项违规`
      : '复验返回通过，但缺少逐项观测';
  }
  const failed=before?.checks?.filter(c=>!c.passed).length || 0;
  if (verified) return `${failed} 项失败检查已通过复验`;
  if (before) return `${Array.isArray(issues) ? issues.length : failed} 项${Array.isArray(issues) ? '违规' : '检查未通过'}，${repaired ? '已修复，等待复验' : '等待处理'}`;
  return '先看清会改坏什么，再动手';
}
