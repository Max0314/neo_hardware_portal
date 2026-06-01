-- MySQL数据库和用户设置SQL脚本
-- 使用方法: mysql -u root -p < scripts/setup_mysql_database.sql
-- 或者: sudo mysql < scripts/setup_mysql_database.sql

-- 注意: 请先设置环境变量 MYSQL_PASSWORD
-- export MYSQL_PASSWORD='your_password'

-- 创建数据库
CREATE DATABASE IF NOT EXISTS htmlsystm CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 删除已存在的用户（如果存在，避免冲突）
DROP USER IF EXISTS 'htmlsystm_user'@'localhost';

-- 创建用户（密码需要手动替换）
-- 请将 'Zzw5221331' 替换为实际密码
CREATE USER 'htmlsystm_user'@'localhost' IDENTIFIED BY 'Zzw5221331';

-- 授予权限
GRANT ALL PRIVILEGES ON htmlsystm.* TO 'htmlsystm_user'@'localhost';

-- 刷新权限
FLUSH PRIVILEGES;

-- 显示结果
SELECT 'Database and user created successfully' AS status;
SELECT User, Host FROM mysql.user WHERE User='htmlsystm_user';
SHOW GRANTS FOR 'htmlsystm_user'@'localhost';

