# Task 006 - 增加姜海洋管理员权限

## 状态

已实现并已在生产执行。

## 分支

`fix/task-002-008-hardware-feedback`

## 修复结果

- 新增幂等 SQL：`migration/grant-jiang-haiyang-admin.sql`。
- 目标用户：`20059616 / 姜海洋`。
- 授权结果：`admin,management,user`。
- 未添加 `super_admin`。

## 线上复查

2026-06-04 已通过 SSH 连接 `52.76.165.169` 执行幂等 UPDATE。

复查到 active 管理权限账号：

- `zzw`：`admin,management,super_admin`
- `20461992 / 张志伟`：`admin,user,super_admin`
- `20461982 / 陈鹏列`：`admin,user`
- `20059616 / 姜海洋`：`admin,management,user`

## 验证

- 已执行：生产库角色更新与管理员名单复查。
