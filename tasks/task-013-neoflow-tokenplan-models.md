# Task 013：硬件门户接入 NeoFlow Token Plan 模型

## 状态

- 交付分支：`fix/task-013-neoflow-tokenplan-models`
- Worktree：`D:\code_CPL\.codex-worktrees\hardware-neoflow-tokenplan`
- 基线：`github/main` `e087066`
- 当前状态：未提交

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
