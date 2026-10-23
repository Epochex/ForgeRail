# Evidence-first workbench implementation plan

**Goal:** 新手能解释每个 case 实际改了什么、为何失败、修复范围和复验证据；面试中的效果主张有明确分母和边界。

**Authorization:** 用户明确要求直接修改，沿用已批准的单工作台、16 case 和 Lab 执行范围，不再进入设计确认。

**Architecture:** 原有 Python 执行器和 SQLite journal 保持权威；新增教学投影负责把观察转为可读内容，独立评测报告读取固定测试集的 JUnit。原生 ES modules，无新增依赖。

**Tradeoff:** 不重写成 React，不增加 Agent 或主观模型评分。采用具体事故叙事、并排数值和可展开原始凭据；保留开发者深挖能力，降低首屏信息量。

## Tasks
- [x] 1. `tests/test_lab_evaluation.py` 先验证缺测、跳过、重复、失败不能计算为通过；`lab/evaluation.py` 和 `scripts/evaluate_lab.py` 生成固定 41 样本报告，记录来源、版本、环境和原始 XML。
- [x] 2. `lab/walkthrough.py` 为 16 case / 41 变体提供具体操作说明。`web/incident.js` 展示当前变体、失败规则、修复范围、实测前后对照和定向证据。原始记录/时间线默认折叠，去掉重复结果卡和泛化建议。
- [x] 3. 浏览器验证具体坏值、修复依据、旧 run 兼容、切换变体不串结论；跑完整 E2E 和评测，记录真实结果与未证明事项。

## Review focus
历史数据缺少字段时不能补造修复值；切换变体不能复用旧 run 成功；失败/取消不能被隐藏；样本同源偏差和人工复核缺失须可见；没有报告或代码变化时不能显示当前成功率。
