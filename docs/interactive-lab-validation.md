# 交互实验台验收记录

日期：2026-10-23。本次实现基于 `bf2b6ff` 的已批准设计；实际操作不启动 Unity、Player、Jenkins、Docker 或平台 SDK。

## 本机实测

| 验证 | 结果 | 证据/口径 |
| --- | --- | --- |
| 原核心 + Lab 完整 Python 回归 | **168 passed, 2 skipped**，187.70 秒 | `python -m pytest -q --junitxml=runtime/interactive-final-pytest.xml` |
| Lab 后端范围 | 67 项，其中 66 通过、1 个 POSIX 专用跳过 | 完整回归内包含；16 家族/41 变体闭环，以及 API/准入/安全/恢复/进程边界 |
| 原核心范围 | 102 通过、1 个官方 Unity 引用程序集检查跳过 | 完整回归内包含，原 CLI/API 兼容性保留 |
| 浏览器完整回归 | **22 passed**，约 3.6 分钟 | Windows Edge、真实 HTTP，无 Lab 响应 mock；16 默认案例加下载/窄屏/键盘/取消/租约接管/变体与跳转 |
| 补充浏览器回归 | **2 passed**，8.7 秒 | 增强文件预览/真实下载/导出/窄屏路径，以及新增空筛选/角色/离线恢复；共覆盖最终 23 个登记测试 |
| 独立进程 HTTP 验收 | 16 默认案例全部 verified | `runtime/http-final-acceptance-results.json`；每个动作独立进程；后续 05/09 加强由上述 Python/浏览器覆盖 |
| wheel 分发 | 9 个前端静态资源随包分发，独立虚拟环境加载并完成 6 动作 | `uv build --wheel`、安装 `.whl`；确认导入来自 `site-packages`，静态页面和 case01 均通过 |
| 独立代码审查 | 重要发现已修复并补回归 | 中断重试、指定故障识别、实际 HTTP 节点、取消/超时传播、UI 状态误报与变体/键盘问题 |

本机两个跳过分别为：Windows 不运行 POSIX 服务死亡/进程组专用回归；未安装官方 Unity 引用程序集而跳过该合约检查。其余测试未因缺少引擎而隐藏 Lab 失败。两条依赖弃用提示不影响此次测试，但后续升级需处理。

## 持续验收

GitHub Actions 配置 Windows/Linux Python 矩阵及 Linux Chromium 全部浏览器测试。Linux 执行本机跳过的 POSIX 服务死亡回归。实际远端运行结果请查看 [CI](https://github.com/Epochex/ForgeRail/actions/workflows/ci.yml)，本机结果与远端结果分别记录。

## 界面与复现

- [桌面工作台截图](assets/interactive-lab-desktop.png)
- [窄屏工作台截图](assets/interactive-lab-mobile.png)
- [启动与使用](interactive-lab.md)
- [开发演进、架构与取舍](interactive-lab-retrospective.md)

建议面试演示：01 解释资源检查前移；06 解释出包与可运行的区别；09 解释租约、接管及旧代次拒绝；13/14 解释制品身份与发布回滚。每例先说明失败判据，再展示实际变化和复验断言。

证据支持本地 Lab 机制和这些测试条件下的行为，不支持真实 Unity/Android/iOS 出包、生产性能改进或企业内部架构结论。
