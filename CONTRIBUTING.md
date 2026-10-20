# Contributing to ForgeRail

优先处理可以复现的构建、制品完整性与恢复问题。按 README 安装 Python 3.11+ 与锁定依赖，再以 editable 模式安装项目。导入路径为 `gamebuild`。

修改前创建分支；修改后运行：

```bash
python -m pytest -q
python -m gamebuild.cli demo --root runtime/contribution --report runtime/contribution.json
git diff --check
```

涉及 Unity 合约时，额外使用 .NET SDK 9 执行：

```bash
dotnet run --project tests/unity_contracts/UnityContracts.csproj --configuration Release
```

引擎修改需要固定 Editor 上的实际验证。没有 Editor 时可以提交修复，但须说明未运行项，不能把静态检查或 mock 当成引擎运行。

## 提交要求

- 说明具体触发条件、修改后的行为和回归验证。
- 并发、取消、缓存和恢复问题应断言失败后的状态。
- 不依赖测试顺序，不使用真实企业服务和业务数据。
- Unity 资源与对应 `.meta` 一起提交；保持精确 Editor 版本。
- 不提交凭据、license、本机标识、安装包、Player ZIP 或缓存。
- 不改写已有历史验收 JSON；新实验注明平台、源码与执行范围。
- 修改依赖后更新 `requirements.lock`，说明必要性和上游许可。

Issue 请提供 OS、Python、工具版本、脱敏命令、预期结果和最小复现。PR 尽量只解决一个问题，附实际测试结果及未运行项。
