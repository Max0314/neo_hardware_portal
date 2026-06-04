# Task 008 - NEO Hardware AI UI 统一

## 状态

已实现。

## 分支

`fix/task-002-008-hardware-feedback`

## 修复结果

- 新增共享顶部动作样式：`neo-page-actions`、`neo-page-action`。
- Dashboard、Leaderboard 的返回/外部打开动作统一为左上角动作组。
- BOM 对比、网表对比、替换对管理补齐外部打开，并统一左上返回按钮样式。
- 物料数据库独立 HTML 页面将“返回 NEO”移动到左上角，并新增“外部打开”。
- GroupChatRoom/BOM check/原理图页面左上区域新增外部打开图标按钮。
- 未修改业务逻辑、数据流、AI 功能和原有主操作入口。

## 验证

- 已执行：`cd neo_ai_chatroom && npm run build`。
- 结果：前端构建被既有 TypeScript 错误阻塞，详见 Task 003。
- 人工验证：左上角可见返回/外部打开，核心工具功能不受影响。
