-- 创建安全相关的数据库表

-- IP黑名单表
CREATE TABLE IF NOT EXISTS `ip_blacklist` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `ip_address` VARCHAR(45) NOT NULL COMMENT 'IP地址',
  `block_until` DATETIME NOT NULL COMMENT '封禁到期时间',
  `reason` VARCHAR(255) DEFAULT NULL COMMENT '封禁原因',
  `created_time` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  UNIQUE KEY `uk_ip` (`ip_address`),
  KEY `idx_block_until` (`block_until`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='IP黑名单表';

-- 登录失败记录表（可选，用于审计）
CREATE TABLE IF NOT EXISTS `login_attempts` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `ip_address` VARCHAR(45) NOT NULL COMMENT 'IP地址',
  `username` VARCHAR(100) DEFAULT NULL COMMENT '用户名',
  `success` TINYINT(1) DEFAULT 0 COMMENT '是否成功',
  `created_time` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '尝试时间',
  KEY `idx_ip` (`ip_address`),
  KEY `idx_created_time` (`created_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='登录尝试记录表';

-- 验证码 Token（跨 worker 共享）
CREATE TABLE IF NOT EXISTS `captcha_tokens` (
  `token` VARCHAR(64) PRIMARY KEY COMMENT '验证码 token',
  `code_hash` VARCHAR(64) NOT NULL COMMENT '验证码 SHA256 哈希',
  `expires_at` DOUBLE NOT NULL COMMENT '过期 Unix 时间戳',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  KEY `idx_expires_at` (`expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='图形验证码 Token 表';

-- NEO 积分上报失败补偿队列
CREATE TABLE IF NOT EXISTS `neo_points_pending` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `user_key` VARCHAR(128) NOT NULL COMMENT '用户标识',
  `event_type` VARCHAR(64) NOT NULL COMMENT '积分事件类型',
  `attempts` INT NOT NULL DEFAULT 0 COMMENT '已重试次数',
  `last_error` VARCHAR(512) DEFAULT NULL COMMENT '最后一次错误',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='NEO 积分上报失败补偿表';

