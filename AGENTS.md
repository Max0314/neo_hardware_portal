# AGENTS.md

本文件是 `neo_hardware_portal/neo_hardware_portal` 的 AI 工程化约束。Codex 或其他 AI Agent 修改本项目时，应优先读取本文件、`README.md`、`docs/workflow.md`、`docs/architecture.md`、`docs/coding-style.md` 和对应的 `tasks/*.md`。

## 项目边界

- 本项目是硬件研发部系统的 Docker Compose 单机栈，GitHub 主分支为 `main`。
- 包含 `htmlsystm`、`neo_ai_chatroom`、统一网关、迁移脚本和运维文档。
- 不属于 `SOP`、`ai_code_review`、`bi_center` 或 `motion_analysis` 的运行时。
- `.env`、证书私钥、数据库卷、上传文件、备份包和生产导出数据不进入 Git。

## 技术栈

- 多服务 Docker Compose。
- `htmlsystm`：Python 服务和模板。
- `neo_ai_chatroom`：前端、后端和工具页面。
- `gateway/`：统一入口配置。
- `migration/`、`scripts/`：部署、迁移和运维脚本。

## 编码规则

- 修改一个服务时避免牵连其他服务。
- 部署脚本必须保持可重复执行，失败时应有明确错误信息。
- 密码、token、证书、Cookie 和生产主机信息按敏感信息处理。
- 前端改动需要检查构建入口和路径前缀。
- 后端改动需要考虑数据卷、迁移和历史数据兼容性。

## 验证规则

默认验证入口：

```bash
make check
```

至少运行 `make compile`；涉及前端时运行对应构建或说明依赖不可用。

## Git 规则

- 主分支为 `main`。
- 一个任务一个分支，推荐格式：`feature/task-xxx-short-name` 或 `fix/task-xxx-short-name`。
- 提交前确认 `.env`、证书私钥、数据卷、备份、日志和构建产物没有进入暂存区。
