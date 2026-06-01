-- 创建安全相关数据库表
-- 执行方法: mysql -u用户名 -p数据库名 < CREATE_SECURITY_TABLES.sql

-- 创建 IP 黑名单表
CREATE TABLE IF NOT EXISTS `ip_blacklist` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `ip_address` VARCHAR(45) NOT NULL UNIQUE COMMENT 'IP地址',
    `block_until` DATETIME NOT NULL COMMENT '封禁到期时间',
    `reason` VARCHAR(255) DEFAULT NULL COMMENT '封禁原因',
    `created_time` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX `idx_ip_address` (`ip_address`),
    INDEX `idx_block_until` (`block_until`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='IP黑名单表';

-- 创建登录尝试记录表（可选，用于审计）
CREATE TABLE IF NOT EXISTS `login_attempts` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `ip_address` VARCHAR(45) NOT NULL COMMENT 'IP地址',
    `username` VARCHAR(100) DEFAULT NULL COMMENT '用户名',
    `success` TINYINT(1) DEFAULT 0 COMMENT '是否成功',
    `created_time` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '尝试时间',
    INDEX `idx_ip` (`ip_address`),
    INDEX `idx_username` (`username`),
    INDEX `idx_created_time` (`created_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='登录尝试记录表';

