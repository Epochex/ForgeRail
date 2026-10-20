# Unity 真实构建链路

项目固定 **Unity 6000.3.0f1 / d1870ce95baf**，Windows x64、Mono 后端；版本来自 [Unity 官方 release 页面](https://unity.com/releases/editor/whats-new/6000.3.0f1)。这是为演示固定的可安装补丁，不表示当前最新版本。安装脚本使用该页的官方下载源，验证 Windows Authenticode 签名与 Unity 发布者，并记录安装包 SHA256。Editor 安装在本工程的 `runtime/tools/unity/`，不替换系统工具。

```powershell
./scripts/install-unity.ps1
```

Unity Personal/Pro 需要有效授权。历史实验机器曾通过真实 batch 验证，不表示新机器已具备授权；新机器若缺少授权，在 Unity Hub 中使用 Locate 指向 `runtime/tools/unity/6000.3.0f1/Editor/Unity.exe`，由本人完成激活后重跑。脚本不接收账号密码，不提交 license 文件，也不会绕过授权。以实际 batch 结果判断授权可用性，非阻塞的 headless entitlement 警告不能当成缺少许可证。参阅 [官方安装参数](https://docs.unity.com/en-us/engine/6000.0/manual/get-started/install-and-upgrade/getting-started-installing-unity/installing-unity) 和 [Editor 命令行参数](https://docs.unity.cn/6000.3/Documentation/Manual/EditorCommandLineArguments.html)。

构建请求文件示例（`output_dir` 必须替换为绝对路径，且在 Unity 项目目录之外；每次使用新目录）：

```json
{
  "build_id": "20261020-abcd1234-demo",
  "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "input_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "output_dir": "C:/gamebuild-output/demo-001",
  "target": "StandaloneWindows64",
  "configuration": "Release"
}
```

上面 SHA 仅说明格式，真实流水线必须使用固定源码提交和计算所得输入摘要。入口拒绝短 SHA、非法 digest、不支持的目标/配置、输出与项目重叠以及覆盖既有构建。入口不验证 SHA 对应源码；该职责属于创建独立 worktree 的 worker。

```powershell
./scripts/build-unity.ps1 -Request ./runtime/request.json -EditorTests
./scripts/build-unity.ps1 -Request ./runtime/request.json -Smoke
```

第一条在真实 Editor 中创建 Missing Script prefab 和非法纹理导入设置，确认检查拒绝，再删除临时资源并检查干净项目。没有 Editor 时该项为 `blocked`。第二条构建并启动真实 Player；`reports/unity/<run>/invocation.json` 记录命令、退出码及状态，旁边保存 Editor / Player 日志和 smoke 回执。失败不产生通过记录。默认 Editor 超时 900 秒、Player 45 秒，只终止本次创建的进程树。

直接引擎调用和 worker 集成：

```powershell
& ./runtime/tools/unity/6000.3.0f1/Editor/Unity.exe -batchmode -nographics -quit `
  -projectPath '<managed-worktree>/unity/BuildLab' -buildTarget Win64 `
  -executeMethod GameBuild.BuildEntry.Build -buildRequest '<absolute-request.json>' `
  -logFile '<attempt-directory>/editor.log'
& '<output_dir>/player/GameBuildLab.exe' -batchmode -nographics `
  --smoke-output '<output_dir>/smoke.json' -logFile '<attempt-directory>/player.log'
```

实际产物：

| 路径 | 证据 |
| --- | --- |
| `player/GameBuildLab.exe` 及相邻 Data/Mono 目录 | `BuildPipeline.BuildPlayer` 真正生成的 Windows Player |
| `build-report.json` | 引擎结果、时间、大小、错误/警告数、资源问题、依赖文件/metadata 摘要、资源包大小及摘要 |
| `build-info.json` | build ID、完整 SHA、输入摘要、目标、配置、引擎版本、配置与资源包 SHA256 |
| `bundles/demo` 及 manifest | 引擎实际导出的 AssetBundle 与依赖元数据 |
| `player/GameBuildLab_Data/StreamingAssets/GameBuild/` | Player 内嵌身份文件和实际加载的 bundle |
| `smoke.json`（worker 指定路径） | 匹配身份、`adapter=unity`、`asset_loaded=true`、`status=passed` 后才准入 |

`AssetChecks` 通过 Unity 导入数据库检查配置、场景/prefab Missing Script、丢失引用和纹理导入设置；不自动修复资源。构建入口生成固定场景（平面、方块、灯光、相机），将配置导出为 AssetBundle，再构建 Player。Player 校验 bundle 和配置 SHA256，调用 `AssetBundle.LoadFromFile` 和 `LoadAsset<TextAsset>`，完成一帧后输出回执并退出。可视模式运行会显示版本信息，WASD/方向键移动方块。无图形 smoke 只证明初始化和资源加载；渲染及真实窗口需单独验收。

报告中的 `resource_input_digest` 绑定实际引擎版本、目标、导出器版本与源码 SHA256，以及 `AssetDatabase.GetDependencies` 返回的文件内容与 `.meta` 摘要，作为不可变资源导出缓存键。默认缓存位于每个 worktree 的 `Library/GameBuildBundleCache`，可通过 Editor 参数 `-assetCacheDir <工程专用共享目录>` 或包装脚本 `-AssetCacheDirectory` 指定跨 worktree 的不可变导出缓存。缓存条目通过目录 rename 发布，存在的有效条目不能覆盖；读取校验完整索引、文件大小与 SHA256，复制后再次验证，污染条目隔离后重新导出。报告分别记录查找、命中和导出时间。控制面静态检查缓存与引擎导出缓存分别记录；.NET 文件测试通过不表示已测得 Unity 资源包命中，真实时延仍以实际引擎报告为准。

每个 worktree 仅允许一个 Editor，`Library/` 不共享。`Assets/Generated/` 与 `Assets/StreamingAssets/` 是声明的生成目录，已由项目 `.gitignore` 排除；worker 输入摘要也必须排除。其余资源 `.meta` 作为源码提交。不要在用户工作区中构建后以生成文件修改源码身份。

可脱离 Editor 执行的验证：

```powershell
python -m pytest tests/test_unity_contracts.py -q
dotnet run --project tests/unity_contracts/UnityContracts.csproj --configuration Release
```

这只编译和执行共享的纯 C# 请求/摘要/回执及缓存文件合约，另检查包装脚本的缺失 Editor 和中文 UTF8 请求处理。安装了官方 Editor 时，也执行其真实 API 引用的 .NET 编译；这些均不代替 Unity 执行、资源语义、Player 或 A01/A03 验收。所有 .NET 测试使用各自临时 obj/bin 目录，可与其他 suite 并发运行。

2026-10-20 实测记录位于 `reports/unity/engine-status.json`：官方 Editor 安装签名 Valid，真实 Editor 三项资源检查通过，Windows Mono Player 冷构建和 Release 构建均成功，运行回执确认 AssetBundle 已加载。真实可视窗口见 `reports/unity/player-window.png`。两个实际 Git 分支 `demo/unity-base` 与 `feature/resource-change` 在不同 worktree/Library 中同时构建，执行窗口重叠 64.30 秒，源码与资源身份均不同，记录于 `reports/unity/parallel.json`；这是同机两个逻辑构建，不是跨主机集群验证。

`reports/unity/export-cache.json` 记录真实引擎的冷 miss、不变输入 hit、资源变更 miss、污染隔离与重新导出，恢复后的 Player 通过资源加载和身份校验。原始时延不概括成性能提升比例。最后的可视验收使用 Release；Development 调试连接可能触发 Windows 防火墙提示，实验没有允许访问或修改防火墙规则。提交的日志已脱敏，原始日志只留在本机被忽略的 `secrets-*` 路径。

源实现的 API 依据：[BuildPlayer](https://docs.unity.cn/6000.3/Documentation/ScriptReference/BuildPipeline.BuildPlayer.html)、[BuildAssetBundles](https://docs.unity.cn/6000.3/Documentation/ScriptReference/BuildPipeline.BuildAssetBundles.html)、[GetDependencies](https://docs.unity.cn/6000.3/Documentation/ScriptReference/AssetDatabase.GetDependencies.html)。
