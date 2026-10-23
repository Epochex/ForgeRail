const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

const steps = ['prepare', 'inject', 'execute', 'diagnose', 'repair', 'verify'];
const phases = ['prepared', 'injected', 'reproduced', 'diagnosed', 'repaired', 'verified'];

test.beforeEach(async ({ page }) => {
  await page.goto('/?access=browser-acceptance-only');
  await expect(page.getByTestId('case-01')).toBeVisible();
});

test('novice can explain the actual fault, repair scope and evidence limits', async ({page}) => {
  await page.getByTestId('case-01').click();
  await page.getByTestId('fault-variant').selectOption('import');
  await page.getByTestId('run-all').click();
  await expect(page.getByTestId('workbench')).toHaveAttribute('data-phase','verified');
  const story = page.getByTestId('incident');
  await expect(story).toContainText('Assets/hero_texture.txt.meta');
  await expect(story).toContainText('compression');
  await expect(story).toContainText('readable');
  await expect(story).toContainText('none');
  await expect(story).toContainText('compressed');
  await expect(story).toContainText('2 项违规 → 0 项违规');
  await expect(story).toContainText('恢复范围大于两个字段');
  await expect(page.locator('#audit')).not.toHaveAttribute('open','');
  fs.mkdirSync('output/playwright', {recursive:true});
  await page.screenshot({path:'output/playwright/incident-overview.png',fullPage:false});
  await page.getByRole('button',{name:'查看修复差异'}).click();
  await expect(page.locator('#audit')).toHaveAttribute('open','');
  await expect(page.locator('#evidence-action option:checked')).toContainText('应用修复');
  await page.getByTestId('fault-variant').selectOption('budget');
  await expect(story).toContainText('1024');
  await expect(story).not.toContainText('2 项违规 → 0 项违规');
  await page.locator('#trust-summary').click();
  await expect(page.getByTestId('trust')).toContainText('同源');
  await expect(page.getByTestId('trust')).toContainText('人工复核尚未开展');
  await expect(page.getByTestId('trust')).toContainText('Agent');
});

test('a failed recheck displays actual post-repair values and new violations', async ({page}) => {
  await page.getByTestId('case-01').click();
  await page.getByTestId('fault-variant').selectOption('import');
  await page.getByTestId('new-run').click();
  for (let i=0;i<5;i++) {
    await page.getByTestId(`step-${steps[i]}`).click();
    await expect(page.getByTestId('workbench')).toHaveAttribute('data-phase',phases[i]);
  }
  const rid=await page.getByTestId('workbench').getAttribute('data-run-id');
  const root=JSON.parse(fs.readFileSync('runtime/browser-test-root.json','utf8'));
  const fixture=path.join(root,'runs',rid,'fixture','Assets');
  const meta=path.join(fixture,'hero_texture.txt.meta');
  fs.writeFileSync(meta,fs.readFileSync(meta,'utf8').replace('compressed','none'));
  fs.writeFileSync(path.join(fixture,'hero_texture.txt'),'x'.repeat(1024));
  await page.getByTestId('step-verify').click();
  await expect(page.getByTestId('run-status')).toContainText('执行异常');
  await expect(page.getByTestId('incident')).toContainText('复验仍有失败');
  const compression=page.locator('.outcome-table tbody tr').filter({hasText:'compression'});
  await expect(compression.locator('td').last()).toHaveText('none');
  await expect(page.getByTestId('incident')).toContainText('1024');
  await expect(page.getByTestId('incident')).not.toContainText('尚未复验');
});

for (let i = 1; i <= 16; i++) {
  const id = String(i).padStart(2, '0');
  test(`case ${id}: actual fault → diagnosis → repair → verification`, async ({ page }) => {
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.getByTestId(`case-${id}`).click();
    await page.getByTestId('new-run').click();
    const workbench = page.getByTestId('workbench');
    await expect(workbench).toHaveAttribute('data-phase', 'created');
    for (let n = 0; n < steps.length; n++) {
      await page.getByTestId(`step-${steps[n]}`).click();
      await expect(workbench).toHaveAttribute('data-phase', phases[n]);
      if (steps[n] === 'execute') {
        await expect(page.getByTestId('run-status')).toContainText('问题已复现');
        await expect(page.getByTestId('checks')).toContainText('未通过');
      }
      if (steps[n] === 'prepare' || steps[n] === 'inject' || steps[n] === 'repair') {
        await expect(page.getByTestId('checks')).not.toContainText('已捕获预期故障');
      }
    }
    await expect(page.getByTestId('run-status')).toContainText('复验通过');
    await expect(page.getByTestId('evidence-panel')).toContainText('Lab');
    const rid = await workbench.getAttribute('data-run-id');
    const response = await page.request.get(`/lab/api/runs/${rid}`);
    const run = await response.json();
    expect(run.actions.find(a => a.kind === 'execute').result.passed).toBe(false);
    expect(run.actions.find(a => a.kind === 'verify').result.passed).toBe(true);
    expect(run.actions.every(a => a.state === 'SUCCEEDED')).toBe(true);
    expect(run.events.some(e => e.data?.duration_ms >= 0)).toBe(true);
    expect(run.evidence.length).toBeGreaterThan(0);
    await page.reload();
    await expect(workbench).toHaveAttribute('data-phase', 'verified');
    expect(errors).toEqual([]);
    if (id === '01' || id === '14') {
      fs.mkdirSync('output/playwright', { recursive: true });
      await page.screenshot({ path: `output/playwright/case-${id}-desktop.png`, fullPage: true });
    }
  });
}

test('complete demo, evidence download, export and narrow layout', async ({ page }) => {
  await page.getByTestId('case-12').click();
  await page.getByTestId('run-all').click();
  await expect(page.getByTestId('workbench')).toHaveAttribute('data-phase', 'verified');
  const rid = await page.getByTestId('workbench').getAttribute('data-run-id');
  const run = await (await page.request.get(`/lab/api/runs/${rid}`)).json();
  const ev = run.evidence[0];
  expect((await page.request.get(`/lab/api/runs/${rid}/evidence/${ev.id}`)).ok()).toBe(true);
  await page.locator('#audit > summary').click();
  await page.getByRole('tab', {name:/证据文件/}).click();
  await page.locator('.file-open').first().click();
  await expect(page.locator('#file-content')).not.toContainText('正在读取实际文件');
  const evidenceDownload=page.waitForEvent('download');
  await page.locator('.file-download').first().click();
  expect((await evidenceDownload).suggestedFilename()).toMatch(/\.(json|diff|log|txt)$/);
  const download = page.waitForEvent('download');
  await page.getByTestId('export-run').click();
  expect((await download).suggestedFilename()).toMatch(/forgerail.*json/);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId('run-status')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  fs.mkdirSync('output/playwright', { recursive: true });
  await page.screenshot({ path: 'output/playwright/mobile.png', fullPage: true });
});

test('search, roles, invalid sequencing and keyboard navigation', async ({ page }) => {
  await page.getByTestId('case-search').fill('缓存');
  await expect(page.getByTestId('case-07')).toBeVisible();
  await expect(page.getByTestId('case-03')).toHaveCount(0);
  await page.getByTestId('case-search').fill('');
  await page.getByTestId('case-03').click();
  await page.getByTestId('new-run').click();
  await expect(page.getByTestId('step-verify')).toBeDisabled();
  await expect(page.getByTestId('step-prepare')).toBeEnabled();
  await page.getByTestId('step-prepare').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('workbench')).toHaveAttribute('data-phase', 'prepared');
});

test('cancel a running operation and retain the recoverable record', async ({ page }) => {
  await page.getByTestId('case-10').click();
  await page.getByTestId('new-run').click();
  await page.getByTestId('step-prepare').click();
  await page.getByTestId('cancel-run').click();
  await expect(page.getByTestId('run-status')).toContainText('已取消');
  await expect(page.getByTestId('workbench')).toHaveAttribute('data-phase', 'created');
  await page.reload();
  await expect(page.getByTestId('run-status')).toContainText('已取消');
});

test('lease takeover runs backup attempt and rejects old owner through browser', async ({ page }) => {
  await page.getByTestId('case-09').click();
  await page.getByTestId('fault-variant').selectOption('lease');
  await page.getByTestId('run-all').click();
  await expect(page.getByTestId('workbench')).toHaveAttribute('data-phase','verified');
  const rid = await page.getByTestId('workbench').getAttribute('data-run-id');
  const run = await (await page.request.get(`/lab/api/runs/${rid}`)).json();
  const facts = run.actions.find(a=>a.kind==='verify').result.facts;
  expect(facts.claims.map(c=>c.attempt)).toEqual([1,2]);
  expect(new Set(facts.claims.map(c=>c.pid)).size).toBe(2);
  expect(facts.old_report.status).toBe(409);
  expect(facts.worker_result.download.bytes).toBeGreaterThan(0);
});

test('cancel active child process, retain evidence and retry execution', async ({ page }) => {
  await page.getByTestId('case-10').click();
  await page.getByTestId('new-run').click();
  for (const [kind,phase] of [['prepare','prepared'],['inject','injected']]) {
    await page.getByTestId(`step-${kind}`).click();
    await expect(page.getByTestId('workbench')).toHaveAttribute('data-phase',phase);
  }
  const rid=await page.getByTestId('workbench').getAttribute('data-run-id');
  await page.getByTestId('step-execute').click();
  const root=JSON.parse(fs.readFileSync('runtime/browser-test-root.json','utf8'));
  let stateFolder;
  await expect.poll(()=>{
    const output=path.join(root,'runs',rid,'output');
    for(const action of fs.readdirSync(output)) {
      const candidate=path.join(output,action,'process-state');
      const heartbeat=path.join(candidate,'heartbeat.txt');
      if(fs.existsSync(path.join(candidate,'child.pid')) && fs.existsSync(heartbeat) && fs.statSync(heartbeat).size>0) { stateFolder=candidate; return true; }
    }
    return false;
  },{intervals:[10,20,20]}).toBe(true);
  await page.getByTestId('cancel-run').click();
  await expect(page.getByTestId('run-status')).toContainText('已取消');
  const heartbeat=fs.readFileSync(path.join(stateFolder,'heartbeat.txt'),'utf8');
  await new Promise(resolve=>setTimeout(resolve,250));
  expect(fs.readFileSync(path.join(stateFolder,'heartbeat.txt'),'utf8')).toBe(heartbeat);
  await page.reload();
  await page.getByTestId('step-execute').click();
  await expect(page.getByTestId('workbench')).toHaveAttribute('data-phase','reproduced');
});

test('variant change starts a fresh run and skip link preserves selected case', async ({ page }) => {
  await page.getByTestId('case-01').click();
  await page.getByTestId('new-run').click();
  const first=await page.getByTestId('workbench').getAttribute('data-run-id');
  await page.getByTestId('step-prepare').click();
  await expect(page.getByTestId('workbench')).toHaveAttribute('data-phase','prepared');
  await page.getByTestId('fault-variant').selectOption('naming');
  await page.getByTestId('run-all').click();
  await expect(page.getByTestId('workbench')).toHaveAttribute('data-phase','verified');
  const second=await page.getByTestId('workbench').getAttribute('data-run-id');
  expect(second).not.toBe(first);
  expect((await (await page.request.get(`/lab/api/runs/${second}`)).json()).variant).toBe('naming');
  await page.getByTestId('case-03').click();
  await page.locator('.skip-link').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#case-title')).toContainText('热修');
});

test('empty filters and offline failure recover without fabricating a run', async ({page,context})=>{
  await page.getByTestId('case-search').fill('no-such-scenario-987');
  await expect(page.locator('#case-list')).toContainText('没有');
  await page.getByTestId('case-search').fill('');
  await page.getByRole('combobox',{name:'角色筛选'}).selectOption('美术');
  await expect(page.getByTestId('case-01')).toBeVisible();
  await expect(page.getByTestId('case-09')).toHaveCount(0);
  await context.setOffline(true);
  await page.getByTestId('new-run').click();
  await expect(page.getByRole('alert')).toContainText('无法连接本机实验服务');
  await expect(page.getByTestId('workbench')).toHaveAttribute('data-run-id','');
  await context.setOffline(false);
  await page.getByRole('button',{name:'重试连接'}).click();
  await expect(page.getByRole('alert')).toBeHidden();
  await page.getByTestId('new-run').click();
  await expect(page.getByTestId('step-prepare')).toBeEnabled();
});
