# Coding Style

- 多服务改动要保持边界清晰。
- Python 代码优先明确错误处理和日志上下文。
- 前端路径、API base 和网关前缀要同步。
- Shell 脚本使用 `set -euo pipefail`，并输出清晰阶段信息。
- 不在源码中保存真实密码、token、证书私钥或生产主机配置。
