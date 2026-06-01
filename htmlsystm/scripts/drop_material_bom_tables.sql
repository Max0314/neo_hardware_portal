-- 物料管理系统 / BOM匹配 下线清理脚本
-- 执行前请先完成业务停机窗口与数据库备份

START TRANSACTION;

-- 按依赖顺序删除
DROP TABLE IF EXISTS approval_history;
DROP TABLE IF EXISTS pending_materials;
DROP TABLE IF EXISTS library_permissions;

COMMIT;

