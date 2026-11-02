# Task 013：硬件门户接入 NeoFlow Token Plan 模型

## 状态

- 交付分支：`fix/task-013-neoflow-tokenplan-models`
- Worktree：`D:\code_CPL\.codex-worktrees\hardware-neoflow-tokenplan`
- 基线：`github/main` `e087066`
- 当前状态：已合入 main

## 2026-11-02 默认模型切换与业务验收

- 后续交付分支：`fix/default-model-luna-20261102`；运行代码提交：`5a4480680e6e51780d3b02db9a1f2066dd96d237`，已推 GitHub `main` 和任务分支并部署。项目未配置 GitLab remote。
- 当前默认提及为 `TOKENPLAN_DEFAULT_MENTION_MODEL=bailian-gpt6luna`，实际请求 `openai/gpt-6-luna`；以下原始目标中的 Qwen 默认值仅记录首次接入阶段。
- 修复内容：注册 Luna、添加 NeoFlow 模型映射、使用 `reasoning_effort` 而非 Qwen 的 `enable_thinking`，拒绝将 Luna 发到阿里云直连接口。原理图专业默认保持 `bailian-deepseekv4` → `deepseek/deepseek-v4-pro`。
- 本轮未发现需要新增修复的业务故障，复用上一轮 11 项 `backend/tests/test_tokenplan_gateway.py` 单测和真实 `BailianAdapter.get_response` 普通回复验证。相关运行代码未再变动，不重复执行这些验证。

### 真实业务证据

2026-11-02 在 `stack-neo-backend` 内以已部署源码启动一次独立回环 ASGI 进程，使用仅该进程接受的合成身份；HTTP/WebSocket 路由、模型调用、MySQL、OSS 均走实际实现和生产配置。不接入真实用户的 WebSocket，不启用后台记忆抽取、向量或重排，不发送外部通知。

合成验收编号：`codex-synthetic-cf4cc5987c7f`。

| 验收链路 | 实际结果 |
| --- | --- |
| 未勾选模型时 `@tokenplan` 临时激活 | Luna，3 个流式事件，`finish_reason=stop`；用户/巴巴塔/模型共 3 条消息保存，HTTP 回读与最终回复一致 |
| 关闭连接后再次提及并读取上轮验证码 | Luna 正确返回上轮随机验证码；请求含 3 条上下文消息，会话累计 6 条记录 |
| Luna 思考开关 | 默认请求 `reasoning_effort=none`；开启后为 `high`，均真实完成；没有发送 `enable_thinking` |
| 当前问题去重 | 4 次模型请求中，当前用户消息各出现一次 |
| 网表解析与持久化 | 合成 PADS 网表解析为 4 个元件、3 个网络；确认 OSS 对象存在，删除本次结果的本地缓存后 GET 回源成功 |
| 原理图专业评审 | 服务端默认仍为 DeepSeek V4 Pro；`pre_export` 强制 `enable_thinking=false`，24 个流式事件，返回 3 个接口的完整 JSON，`complete=true`、`finish_reason=stop` |
| 评审历史保存/读取 | HTTP 保存后重新读取，合并评审 JSON 与原结果一致 |
| 清理 | 删除本次会话、消息、评审历史及网表缓存/OSS 对象；回查合成数据库记录为 0、OSS 对象不存在 |

运行镜像：`sha256:6e108534d4b3b22b1eb33dd1b970ab6a29e4649f5cd350c689314749849e5bc5`。容器中 `main.py`、`ai/adapters.py`、`ai/bailian_models.py` 的 SHA-256 与准源文件统一换行后相同。

生产栈补充检查：`AUTO_FIX_NEO_TABLES=0 bash migration/check-stack.sh` 通过关键检查，4 个服务 healthy，网关和登录路由正常；后端最近 20 分钟没有 Traceback、ERROR 或模型请求失败。公网 `/neo_hardware/neo/` 返回 200，未登录访问模型和会话 API 返回 401。

验收证据和本地编写的临时探针位于服务器受限权限运维目录 `/home/max/.codex-ops/model-switch-20261102/`：`portal_business_probe.py`、`portal-business.log`、`portal-check-stack.log`。日志不进入 Git；查看时只提取验收摘要，不输出身份或凭据信息。

验收边界：本轮验证了实际业务路由、流式回复、上下文、模型参数、JSON 解析及持久化；合成身份只用于隔离进程，未验证真实用户登录态、浏览器操作或报告导出。运行实现未改变，因此本轮仅同步验收文档，不重建镜像或重启服务。

## 目标

- 保留现有 Token Plan 直连方式作为可回滚配置。
- 新增 NeoFlow 网关模式，通过 NeoFlow OpenAI 兼容接口调用 Token Plan 模型。
- 硬件门户默认模型调整为 `qwen/qwen3.7-plus`。
- NeoFlow 使用独立 `NEOFLOW_API_KEY`，不复用其他系统密钥。

## 验收条件

- `TOKENPLAN_PROVIDER=direct` 时保持原直连接口和模型名。
- `TOKENPLAN_PROVIDER=neoflow` 时使用 `NEOFLOW_BASE_URL`、`NEOFLOW_API_KEY`，并将 Qwen/DeepSeek 映射为 NeoFlow Token Plan 模型 ID。
- NeoFlow 请求不发送 `provider`，由平台按 Token Plan 优先、多 Key 自动切换和 OpenRouter 回退策略路由。
- 非流式与流式调用使用同一套网关解析逻辑。
- 默认 mention 模型为 `bailian-qwen37plus`。
- 单元测试覆盖路由、模型映射和默认模型。

## 正式切换前置条件

NeoFlow 平台需先创建硬件门户独立应用并生成专用 API Key；未满足时仅交付兼容代码，不修改正式环境。
