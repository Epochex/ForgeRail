# 交互式游戏构建工程实验台

安装 README 中的既有 Python 依赖后，运行 `./scripts/start-lab.ps1`，或 `.venv/Scripts/python.exe -m gamebuild.cli lab --open`。Linux 替换为 `.venv/bin/python`。入口绑定 `127.0.0.1:18766`，只允许本机同源操作。重新启动时使用终端打印的新入口地址；历史实验仍保存在 `runtime/interactive-lab`。

## 如何学习一个案例

主界面是一张事故处理单：操作对象 → 实际注入 → 哪条规则失败 → 修复范围 → 新的复验观测。先读这条因果链，再按需展开原始记录。案例 01 明确列出 compression/readable 两项违规，不再用单个总断言的“0/1”代替具体问题。

1. 在左栏选择角色、案例和故障变体，点击“新建实验”。每个实验有独立文件、Git 仓库、输出和状态。
2. 逐步准备、制造问题、执行。执行步骤必须看到该变体对应的失败证据，才能推进；其他意外错误会保持失败，不冒充复现成功。
3. 点击诊断，对照失败断言、实际日志和文件差异。阶段记录可以定位到证据步骤。
4. 点击修复，查看输入变更；点击复验，对照修复前后断言、实际摘要与进程回执。完整演练会依次执行同一条链路。
5. 点击“查看故障差异 / 查看修复差异 / 查看复验原始记录”定位证据；也可以展开“查看原始证据”，在文件页预览或下载日志、JSON、ZIP。刷新与历史选择可以恢复记录。

| 案例 | 覆盖的问题与验证 |
| --- | --- |
| 01 资源策略 | 命名、导入描述、实际文件预算；规则和路径定位 |
| 02 GUID 与引用 | 重复 GUID、丢失引用、损坏 Prefab 描述；受影响场景 |
| 03 热修同步 | 实际 cherry-pick 冲突、三方内容、错误合并行为回归 |
| 04 多版本并行 | 固定 SHA worktree、真实双进程独占锁、分支内容与重叠区间 |
| 05 构建交付 | 固定源码经真实 HTTP worker 编译、测试、打包、启动、上传与独立下载；Release 门禁 |
| 06 出包后异常 | 实际 ZIP 解压后独立进程读取资源和配置，启动失败与正确回执 |
| 07 缓存 | 冷热缓存、遗漏依赖、损坏隔离；摘要和实际命中次数 |
| 08 阶段并行 | 哈希与压缩工作、实测时间线、依赖顺序和内容一致性 |
| 09 节点与队列 | 独立控制面/节点进程、能力与槽位、租约到期后备用 worker、旧代次 HTTP 409 |
| 10 超时取消 | 父子进程退出、心跳停止、旧结果拒绝与新任务完成 |
| 11 环境 | 实测 Git/Python/磁盘/读写；单独展示 Editor/SDK/授权的 fixture 策略 |
| 12 网络 | loopback DNS/TCP/HTTP 分层探测；首个失败层与实测耗时 |
| 13 制品准入 | 真实 ZIP、manifest、SHA256 与构建身份；坏包拒绝和独立复验 |
| 14 发布回滚 | shadow/canary/stable 状态、独立运行观察、指针回滚与重新启动基线 |
| 15 内容更新 | 依赖闭包、实际增量 ZIP；独立客户端应用更新、加载摘要及下载字节 |
| 16 平台矩阵 | Windows/Android/iOS fixture 能力路由；各目标独立 BLOCKED/成功和通用 Lab ZIP |

## 可信度与边界

所有操作执行真实的本地 Git、Python、HTTP、文件和 SQLite。执行结果来自断言；故障复现另有按案例/变体判定的证据条件。运行回执由启动的子进程写出。计时来自单调时钟采样，没有模拟进度或 CPU 火焰图。

**这些结果证明 Lab 中的协议和机制有效。** 不运行 Editor、Unity Player、SDK、Docker 或 Jenkins。资源引用为约束的 Lab 描述；平台产物为通用 ZIP，不是 APK/IPA。环境描述与本机探测分开呈现。本地微型工作负载不能证明大型游戏耗时改善，也不能证明米哈游内部采用同一实现。

每个实验同时只允许一个动作，全局允许两个动作。网络重试携带幂等键；越级请求返回 409。停止后保留证据；服务中断将未完成动作标为 INTERRUPTED。文件变更动作重试会恢复操作前的 fixture/Git 检查点。执行是至少一次重试语义，不声称具有跨外部系统的 exactly-once 保证。

可下载文本证据是脱敏后的不可变副本，下载摘要与登记摘要一致；原始数据库和凭据文件不公开。系统面向受信任的本机用户，不是多租户代码沙箱。历史、检查点和产物会占磁盘；本次没有自动清理策略。停止服务后可手动归档或删除明确指定的整个运行目录。

## 开发验证

```powershell
.venv/Scripts/python.exe -m pytest -q
npm ci
npm run test:unit
npm run test:e2e
.venv/Scripts/python.exe scripts/evaluate_lab.py --root runtime/interactive-lab
```

Windows 浏览器验收使用本机 Edge；Linux 使用 Chromium，先运行 `npx playwright install --with-deps chromium`。浏览器测试启动独立端口 `18767` 和独立运行目录，不依赖正在使用的工作台，不 mock Lab API。

Python 测试覆盖全部登记故障变体；浏览器测试覆盖 16 个默认案例完整六步闭环，以及下载、刷新、筛选、键盘、窄屏、取消等交互。CI 同时配置 Windows/Linux Python 回归和 Linux Chromium 验收；本机通过与远端 CI 状态应分别查看。

详见 [评测口径、面试回答与本次取舍](evidence-and-evaluation.md)、[实现复盘](interactive-lab-retrospective.md)、[设计](superpowers/specs/2026-10-23-interactive-gamebuild-lab-design.md) 和 [代码导航](code-map.md)。
