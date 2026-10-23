# 构建工程代码索引

| 入口 | 作用 | 深挖重点 |
| --- | --- | --- |
| `src/gamebuild/cli.py` | CLI 和实际双节点 HTTP 演示 | 临时服务生命周期、固定 Git 提交、失败返回码 |
| `src/gamebuild/source.py` | 输入摘要、白名单仓库、托管 worktree | 分支名与完整提交的区别，固定输入重算 |
| `src/gamebuild/store.py` | SQLite 权威状态与发布事务 | BEGIN IMMEDIATE、租约代数、blob 与 DB 提交边界 |
| `src/gamebuild/api.py` | Bearer 认证、节点协议和制品上传 | 结构校验、大小限制、冲突与状态码 |
| `src/gamebuild/worker.py` | 能力注册、独立续租、子进程与交付 | 工作区锁、失联结果撤销、实际 Editor 版本 |
| `src/gamebuild/artifacts.py` | 制品清单与 ZIP 校验 | 内容摘要、嵌入身份、路径越界、禁止覆盖 |
| `src/gamebuild/preflight.py` | 可缓存的文件层资源门禁 | key 绑定资源、规则和目标，缓存仍需校验 |
| `src/gamebuild/cache.py` | 不可变文件或目录缓存 | 污染隔离、并发准入和恢复副本校验 |
| `src/gamebuild/checks.py` | 资源和环境预检 | meta/GUID、大小写冲突、磁盘与工具可用性 |
| `src/gamebuild/runner.py` | 实际进程树管理与有界日志 | Windows Job Object、POSIX 进程组、超时取消 |
| `src/gamebuild/diagnostics.py` | 失败证据与网络探测 | 分层诊断、总时间预算、凭据脱敏 |
| `unity/BuildLab/Assets/Editor/` | 引擎检查、AssetBundle 与 Player 构建 | AssetDatabase、Missing Script、BuildReport |
| `unity/BuildLab/Assets/Scripts/` | 请求合约、运行身份与资源加载 | 实际 bundle/config 摘要和 smoke 回执 |
| `ci/Jenkinsfile` | agent 上的实际 CI 阶段和证据归档 | controller 与执行分离、失败后归档 |
| `labs/acceptance.py` | 8 镜像和运行版本实验 | 层缓存、镜像 ID、离线加载、配置漂移 |
| `labs/messaging.py` | Redpanda 崩溃恢复与影子隔离 | 位点提交时序、事件去重、独立副作用账本 |

从 `tests/test_store.py` 的并发、旧执行者和提交中断用例开始走读，再看 `tests/test_worker.py` 的真实 HTTP 链路和 `tests/test_live_cancellation.py` 的执行中取消。阅读源码时把成功路径和失败后状态放在一起解释。

`reports/acceptance.json` 汇总 A01 至 A17；`reports/labs/`、`reports/unity/` 与 JUnit 报告保留各自原始结果。报告中的 source SHA 是对应执行时的源码版本，后续文档提交不会改变那次实测的含义。

## 交互实验台新增入口

`src/gamebuild/lab/` 在既有构建协议之上增加独立实验应用：

| 文件 | 责任 |
| --- | --- |
| `api.py` / `web/` | 同源认证 API、一个工作台及原生 ES 模块视图 |
| `store.py` | SQLite 动作准入、幂等、顺序、事件、不可变证据登记 |
| `service.py` / `runner.py` | 有界动作子进程、取消、重启恢复、输入检查点与实际差异 |
| `context.py` / `sanitize.py` | 命令/文件/计时/断言公共契约、路径约束、脱敏 |
| `catalog.py` / `scenarios/` | 16 案例、41 变体；按资源、源码、构建、系统机制分模块 |
| `scenarios/expectations.py` | 独立判断是否观察到指定故障，避免把其他失败当复现成功 |
| `bridge.py` / `node.py` | 受控控制面和节点进程，复用原 `create_app` / `work_once`，HTTP 上传下载 |
| `tests/test_lab_*.py` / `tests/e2e/` | 变体闭环、故障边界、真实浏览器验收 |

原 `worker.work_once` 新增可选的内部 `lab_builder` 和 `slots` 参数：默认沿用既有协议；交互场景传入受控的编译/测试/独立启动实现，非任意用户脚本插件。
