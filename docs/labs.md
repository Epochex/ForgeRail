# Jenkins、容器与消息恢复实验

这是个人机制复现实验，使用有限合成事件，不把 Python lab adapter 记作 Unity 出包。文末具体编号、时间与源码 SHA 为开源导入前的历史记录；新 checkout 须重新运行，报告中的旧 SHA 不一定存在于公开仓库。

运行：在工程根目录执行 `./scripts/start.ps1`，随后 `./scripts/acceptance-labs.ps1`。默认使用 `py -3`；可传 `-Python ./.venv/Scripts/python.exe`。重复验收可加 `-SkipImages`，沿用已有四轮镜像测量。`./scripts/stop.ps1` 仅停止 Compose 项目 `gamebuildlab`；`-RemoveProjectVolumes` 仅删除该项目 Compose 卷。消息实验保存的独立卷名记录在 messaging.json，供复核，不全局清理 Docker。

Jenkins 地址为 http://127.0.0.1:18980 ，控制面为 http://127.0.0.1:18981 。仅绑定回环，Redpanda 不发布宿主机端口。账号 labadmin 的随机口令保存在忽略的 `.runtime/credentials.json`，API token 保存在忽略的 `.runtime/lab.env`。不将这些文件粘贴到命令、日志或版本库。controller 使用零 executor；独立 Linux agent 通过 WebSocket 接入，agent secret 由 controller 写入专用卷，以文件参数读取。agent 不挂载 Docker socket；容器故障实验由宿主入口独立执行。

Jenkins 流水线在真实 agent 上执行 Python 测试、CLI demo 的实际 HTTP 与两个逻辑节点流程、环境诊断，最后验证已运行的 Docker 实验结果并归档证据。`RUN_UNITY` 参数默认 true：Linux agent 克隆干净源码并固定到 source 阶段记录的完整 SHA，通过 Compose 控制面向登记的 Windows 节点提交真实 Unity 作业，等待 Player 构建及冒烟，再下载并校验已提交 ZIP。归档包含 Unity 包、manifest、BuildReport 和 smoke；验收入口重新从 Jenkins 下载归档包比对 SHA256。Windows worker 由 `--projects` 中的 buildlab 映射取得同一提交，只能在具备精确 Editor 与目标能力时领任务。流水线不会再次伪造容器结果。真正的构建编号、结果、归档文件列表见 `reports/labs/jenkins.json`，控制台见 `jenkins-console.txt`。Linux 容器无 Unity/.NET SDK 的本地检查按测试定义跳过；远端 Windows Unity 阶段仍必须实际成功，才能通过默认 Jenkins 验收。只运行 lab adapter 时可在 Jenkins 页面显式取消 RUN_UNITY，但这种运行不计入完整 A13。

`infra/Dockerfile.targets` 从统一依赖层派生 core、edge、collector、processor、gateway、scheduler、exporter、observer 八目标。`labs/acceptance.py images` 运行冷构建、同输入暖构建、应用版本变化、依赖版本变化四轮，共 32 次实际 Docker build，并逐个启动 Python 模块回读角色和完整 Git SHA。唯一标签包含源码 SHA、随机运行标识与轮次，已存在的标签拒绝复用。`services.json` 另行记录八个冷构建目标的默认 CMD 启动与真实 HTTP `/build-info` 回读，容器使用无外部网络并通过 docker exec 查询回环地址。冷构建定义为每目标 `--no-cache`，基础镜像已经拉取；未清理其他项目缓存。这里的依赖层是标准库与小型锁文件，用来验证缓存失效边界，并不模拟大型依赖安装耗时。各目标秒数、image ID、CACHED 步骤和原始日志均保留，不预设性能收益。

core/edge 实验启动 HTTP `/build-info`，核对 role、完整 SHA、配置版本及 Docker inspect 的运行 image ID。随后启动错误配置、验证拒绝，执行不存在模块导入并确认非零退出，再启动稳定配置并回读。不同镜像 ID 的准入拒绝单独记录。离线流程执行 Docker save，校验 SHA256，移除工程自己的目标标签并核对不存在，截断归档导入必须失败且目标标签仍不存在，随后对完整归档 Docker load 并比对镜像 ID，以 `--pull=never` 启动。原镜像内容保留在工程备份标签，不删除共享镜像。离线 tar 位于忽略的 `.runtime/offline-core.tar`。

Redpanda 使用单分区独立 stable/shadow topic 与 group，使用各自 SQLite 文件。每组输入 12 个合成事件。消费者先把事件唯一键、副作用与本地检查点在同一个 SQLite 事务落盘，再提交 Kafka offset；在第一次写入后直接以退出码 23 终止，未提交消费位点。重启必须看到 12 次投递、1 次幂等重复、12 条最终唯一记录。本地检查点用于观测；恢复依赖 Kafka 已提交位点重放，由唯一键消除副作用重复，不从本地检查点跳过未提交消息。shadow 施加 +100 的独立副作用，stable 总和仍为 66，shadow 总和为 1266，借此验证存储隔离。消息实验 JSON 记录 topic、group、文件、检查点、投递数、重复数与保留卷。

所有主实验输出 `passed|failed`；可选 k3d 与 systemd 未实际运行，明确为 `not_run`。Docker 容器执行不能当作 Pod imageID 或 systemd 重启验收。

官方依据：

- [Jenkins Docker 安装](https://www.jenkins.io/doc/book/installing/docker/)：官方 controller 镜像与 Java 要求。
- [Controller Isolation](https://www.jenkins.io/doc/book/security/controller-isolation/)：controller 与执行节点分离。
- [Pipeline Syntax](https://www.jenkins.io/doc/book/pipeline/syntax/)：agent、阶段、timeout 与 post 归档。
- [Redpanda Quickstart](https://docs.redpanda.com/streaming/current/get-started/quick-start/)：单节点容器实验。

镜像固定摘要写在 infra Dockerfile 与 compose.yaml；实际构建输出和环境清单保留在 reports/labs。54 个 Jenkins 插件的实际解析版本固定在 `infra/jenkins-plugins.lock`，controller 使用该清单和 `--latest=false` 构建；Python 使用工程 `requirements.lock`，消息实验额外固定 kafka-python 2.3.2。

最新独立镜像测量（32 次构建合计四轮，每轮八目标）：冷构建 44.843 秒、暖构建 35.109 秒、应用变化 22.437 秒、依赖变化 22.969 秒。机器同时执行其他工程任务，这些值只描述本次原始记录，不用于推断稳定加速比例。

Compose 持久化探针在无活动构建时才允许重启控制面，使用当前节点不声明的 Editor 能力建立测试任务，核对重启后仍 queued 后立即取消。该虚构版本号只用于隔离协议探针，不代表安装或运行过该 Editor。正在构建时探针记 blocked，避免影响真实节点。

实际完整流水线：Jenkins #2 SUCCESS，耗时 91.873 秒，源码 `6c1207e8fc3be5c63989e230ac62d56982ed555a`。Linux 测试 108 passed / 8 skipped；Windows 节点完成真实 Unity 作业 `20261020T113051Z-6c1207e8-a3842143f1`。提交制品 `artifact-c1c8fca8b7654a2da3e011155045fd9c`，归档包 32,632,400 字节；从 Jenkins 重新下载后 SHA256 为 `c5980d289cbb08cbb8aeb741eb904ce1a755eaf35253c6acd2d62e41f4f8ba4e`。#1 的早期失败与控制台仍保留，未覆盖成成功。
