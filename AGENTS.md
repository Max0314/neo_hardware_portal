# AGENTS.md

本文件是 `neo_hardware_portal` 的 AI 工程化约束。Codex 或其他 AI Agent 修改本项目时，应优先读取本文件、`README.md`、`docs/deployment-guide.md`、`docs/workflow.md`、`docs/git-workflow.md`、`docs/architecture.md`、`docs/coding-style.md` 和对应的 `tasks/*.md`。

## 项目边界

- 本项目部署在 **NeoFlow 平台**（阿里云主应用服务器），GitHub 主分支为 `main`。
- 包含 `htmlsystm`（管理系统）、`neo_ai_chatroom`（NEO 聊天室）、内部网关、迁移脚本和运维文档。
- 不属于 `SOP`、`ai_code_review`、`bi_center` 或 `motion_analysis` 的运行时。
- `.env`、证书私钥、数据卷、上传文件、备份包和生产导出数据不进入 Git。

## 运行架构（平台硬性要求，违反会被回退）

- **数据库不在本栈内**：统一连 NeoFlowData 外部 MySQL（`MYSQL_HOST` 等一律来自 `.env`，
  Compose 中不得出现任何数据库服务）。每应用一个专用账号，权限仅限本库。
- **文件持久化在阿里云 OSS**（`STORAGE_BACKEND=oss`，写通镜像）：本地 Docker 卷只是
  工作缓存，不得把业务文件的唯一副本落在卷或容器文件系统里。锁文件、临时文件除外。
- **网关只绑回环明文 HTTP**（`127.0.0.1:${GATEWAY_PUBLISH_PORT}`，端口段 39020-39029）；
  TLS 由平台 Nginx 统一终止。不得自带证书、不得监听 0.0.0.0。
- **禁止在服务器上编辑代码**：本地改 → push → 服务器 `git pull` → `bash migration/deploy.sh`。
- 反代改动只能写用户级 `~/.nginx/*.conf` 的 `location` 层，改前必须 `sudo nginx -t`。

## 技术栈

- 多服务 Docker Compose（htmlsystm / backend / web / gateway，四容器，无数据库容器）。
- `htmlsystm`：Python 服务和模板，存储层见 `server/object_store.py`、`server/tree_mirror.py`。
- `neo_ai_chatroom`：前端、后端和工具页面；`backend/object_store.py`、`backend/tree_mirror.py`
  是 htmlsystm 同名文件的**副本**（两个镜像构建上下文互不可见），**修改必须同步两份**。
- `gateway/`：统一入口配置。`X-Forwarded-Proto` 必须透传上游值（见 `$forwarded_proto` map），
  网关自身是 HTTP，直接用 `$scheme` 会把外部 https 覆盖成 http，钉钉 OAuth 会拒绝回调。
- `migration/`、`scripts/`：部署、迁移和运维脚本。数据库访问统一走 `migration/_common.sh`
  的 `mysql_cli` / `mysql_dump_cli` / `mysql_reachable`（.env 凭据、密码经 `MYSQL_PWD`
  传递，不进 ps 输出），不得再写 `docker exec` 进数据库容器的形式。

## 编码规则

- 修改一个服务时避免牵连其他服务。
- 部署脚本必须保持可重复执行，失败时应有明确错误信息。
- 密码、token、证书、Cookie 和生产主机信息按敏感信息处理；脚本与验收输出不得打印
  `.env` 中密钥的值，只允许报告"已配置/未配置"。
- 前端改动需要检查构建入口和路径前缀（`PUBLIC_PATH_PREFIX=/neo_hardware`）。
- 后端改动需要考虑数据兼容性：结构化数据在外部 MySQL，文件经写通镜像入 OSS，
  新增文件型功能必须走 `object_store` / `tree_mirror`，不得直接落盘当持久化。

## 验证规则

当前工作模式是 PC 本地开发、Git 管理，经 SSH 到 NeoFlow 服务器部署和验证。优先运行本地可执行检查：

```bash
make quick
make check
```

本地没有 `make`、Docker 或 Linux 虚拟环境路径时，至少运行等价检查：

```bash
python -m compileall -q htmlsystm neo_ai_chatroom/backend scripts migration
cd htmlsystm && python -m pytest server/tests -q
cd neo_ai_chatroom && python -m pytest backend/tests -q
```

涉及前端时运行对应构建或说明依赖不可用；Docker Compose build、服务重启、健康检查和日志检查在服务器通过 SSH 执行（`bash migration/check-stack.sh` 为部署后验收入口）。

## Git 规则

- 主分支为 `main`。
- 一个任务一个分支，推荐格式：`feature/task-xxx-short-name` 或 `fix/task-xxx-short-name`。
- 提交前确认 `.env`、证书私钥、数据卷、备份、日志和构建产物没有进入暂存区。
