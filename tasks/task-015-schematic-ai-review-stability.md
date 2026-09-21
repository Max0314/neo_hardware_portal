# Task 015：原理图 AI 审核长请求稳定性

## Goal

修复原理图 AI 审核在 NeoFlow 迁移后长时间停留在“正在思考”、连接中断后仍继续续写，以及未映射模型被选为默认模型的问题。

## Scope

- 服务：`neo_ai_chatroom` 后端与前端。
- 后端：兼容 NeoFlow `delta.reasoning`，原理图审核关闭思考模式，限制 Token Plan 超时与重试，节流流式推送，去除当前消息的重复上下文。
- 前端：WebSocket 心跳、超时/断线/模型错误终止自动续写、错误状态展示。
- 配置：NeoFlow 模式只展示已有映射的 Token Plan 模型。
- 不修改 NeoFlow 的供应商自动路由策略，请求仍不传 `provider`。

## Verification

- [x] Python 编译检查
- [x] 后端单元测试（26 passed）
- [x] 前端生产构建与 TypeScript 检查
- [ ] NeoFlow 部署及健康检查
- [ ] 生产 Token Plan 流式冒烟测试

## Git

- 分支：`fix/task-015-schematic-ai-review-stability`
- 主分支：`main`

## Deploy

- 服务器：NeoFlow 应用服务器
- 路径：`~/apps/neo_hardware_portal`
- 部署入口：`bash migration/deploy.sh`

## Notes

- `deepseek-v4-flash` 在 NeoFlow 当前模型目录中没有映射，NeoFlow 模式下从原理图默认模型选项中隐藏；可在上游模型就绪后通过显式 `NEOFLOW_MODEL_bailian_deepseekv4flash` 恢复。
- 回滚：回退本任务合并提交后重新执行标准部署脚本。
