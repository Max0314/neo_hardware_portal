# Task 014 - 已发布公告附件更新不生效

## 状态

已实现。

## 分支

`fix/task-014-announcement-attachments`

## 问题原因

- 编辑已发布公告时会复制正式目录生成待审批副本，但附件更新分支是空的 `pass`，随后提前返回，导致新增、替换和删除都未写入待审副本。
- 普通更新分支在没有新附件时会无条件保留全部旧附件，导致只删除附件无效。
- 下载路径会同时遍历待审和正式目录，无法保证页面展示版本与下载版本一致。

## 修复结果

- 新增统一的原子附件对账：提交列表作为最终状态，新文件写入 staging，旧附件按引用保留，未提交文件删除，再原子替换附件目录。
- 已发布公告只更新待审副本；批准后替换正式版本，拒绝后正式版本不变。
- 详情和附件下载显式区分 `published` 与 `pending`，避免正式页面读取未审批附件。
- 新增回归测试覆盖同名替换、新增和删除、只删除全部附件、批准与拒绝。

## 验证

- `python -m pytest htmlsystm/server/tests -q`：65 passed。
- `python -m pytest neo_ai_chatroom/backend/tests -q`：23 passed。
- `python -m compileall -q htmlsystm neo_ai_chatroom/backend scripts migration`：通过。
- 公告详情、编辑器、审核中心三个 HTML 内联脚本已通过 Node.js 语法检查。
