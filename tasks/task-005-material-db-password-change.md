# Task 005 - 物料库修改密码功能

## 状态

已实现。

## 分支

`fix/task-002-008-hardware-feedback`

## 修复结果

- 新增接口：`POST /api/material-db/libraries/{lib_id}/change-password`。
- 管理员角色 `admin`、`management`、`super_admin` 可直接提交 `newPassword` 修改。
- 普通用户必须提交 `oldPassword` 和 `newPassword`，旧密码校验失败返回 403。
- 改密后更新哈希、清除该库 unlock token、写入 `change_password` 审计。
- 物料库页面新增“修改密码”按钮和弹窗。
- 编辑物料库弹窗不再承担改密，避免与上传/编辑流程混用。

## 验证

- 已通过：`python -m compileall -q htmlsystm neo_ai_chatroom\backend migration scripts`。
- 待人工验证：普通用户旧密码错误失败，正确可改；管理员无需旧密码；改密后旧 unlock token 失效。
