# Third-party components

MIT License 适用于本仓库原创代码和文档，不替代第三方许可。

| 组件 | 引用位置 | 使用方式 |
| --- | --- | --- |
| Unity Editor / packages | `unity/BuildLab/Packages/`、安装脚本 | 通过官方渠道单独安装或解析，按 Unity 条款与各包许可使用；不分发 Editor 或 license |
| Python dependencies | `requirements.lock` | 从包索引安装，保留其上游许可 |
| Jenkins / agent / plugins | `infra/`、`infra/jenkins-plugins.lock` | 使用上游容器和插件，各组件许可分别适用 |
| Redpanda | `infra/compose.yaml` | 官方镜像用于本地消息恢复实验，按该版本上游条款使用 |
| Python / OS packages / Java runtime | `infra/` | 从容器与软件仓库取得，镜像附带 notices 继续适用 |
| GitHub Actions | `.github/workflows/ci.yml` | 按各 Action 的上游许可使用 |

第三方二进制不存入此 Git 仓库。摘要和版本提高可追溯性，不保证上游下载服务永久可用。打包或再分发前，核对实际版本的许可证与附带 notices。
