# Task 007 - 删除 NEO 首页活跃评审

## 状态

已实现。

## 分支

`fix/task-002-008-hardware-feedback`

## 修复结果

- 删除 NEO 首页“活跃评审”整块。
- 删除 `NEO Product life cycle` chip 和说明文案。
- 清理对应 CSS。
- 保留“评审效能看板”和 `/dashboard` 独立功能。

## 验证

- 已执行：`cd neo_ai_chatroom && npm run build`。
- 结果：前端构建被既有 TypeScript 错误阻塞，详见 Task 003。
- 已检查：`recent-mini`、`NEO Product life cycle`、`活跃评审` 相关源码引用已清理。
- 人工验证：NEO 首页不再显示图四下方“活跃评审”区域。
