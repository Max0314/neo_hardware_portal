# Task 003 - 钉钉内置浏览器 PDF 导出失败

## 状态

已实现。

## 分支

`fix/task-002-008-hardware-feedback`

## 问题原因

BOM AI check、原理图审核、网表评审结果导出依赖 `window.open('', '_blank')` 后写入 HTML 并调用 `print()`。钉钉内置浏览器会拦截空白新窗口，导致无法导出 PDF。

## 修复结果

- 新增 `neo_ai_chatroom/src/utils/externalOpen.ts`：识别钉钉 UA，优先 `dd.biz.util.openLink({ url })`，再 `window.open`，最后复制链接。
- BOM AI Check 报告、原理图 AI 审核报告、网表评审结果三个导出入口在钉钉内直接引导外部浏览器。
- 普通浏览器保留原打印导出逻辑。
- `GroupChatRoom`、Dashboard、Leaderboard、BOM 对比、网表对比、替换对、物料库页面新增/统一外部打开动作。

## 验证

- 已执行：`cd neo_ai_chatroom && npm run build`。
- 结果：前端构建进入 `tsc` 后被既有 TypeScript 错误阻塞，包括 `AIKeysSettingsModal` 自定义 JSX 标签、多个未使用变量、`GroupChatRoom`/`NetlistResultsPanel` 既有类型不匹配等。
- 新增 `externalOpen.ts` 与本次 PDF 接入点未出现在错误清单中。
- 待人工验证：模拟 DingTalk UA 点击导出，不再只弹“无法打开新窗口”。
