# Task 002 - 公告粘贴图片审批后消失

## 状态

已实现。

## 分支

`fix/task-002-008-hardware-feedback`

## 问题原因

新建公告会经过 `html_sanitize`，原 sanitizer 只允许 `http/https/mailto` 等协议，粘贴图片常见的 `data:image/...;base64,...` 会被剥离。编辑路径没有同样净化，所以用户二次编辑后反而能保留图片。

## 修复结果

- `htmlsystm/server/html_sanitize.py` 允许安全图片 data URL：`png/jpeg/jpg/gif/webp/bmp`。
- 继续禁止 SVG data URL 和非图片 data URL。
- `htmlsystm/server/announcement_manager.py` 在公告更新路径统一净化标题和内容，避免新建/编辑规则不一致。
- 新增 `htmlsystm/server/tests/test_html_sanitize.py` 覆盖允许和拦截场景。

## 验证

- 已通过：`$env:PYTHONPATH='htmlsystm'; python -m unittest server.tests.test_html_sanitize`。
- 已通过：`python -m compileall -q htmlsystm neo_ai_chatroom\backend migration scripts`。
- 备注：本机无 `make` 命令，已按 Makefile 的 `compile` 目标执行等价命令。
