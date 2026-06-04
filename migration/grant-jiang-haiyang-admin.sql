-- Idempotently grant management admin roles to Jiang Haiyang.
-- Target user: username 20059616 / name 姜海洋
UPDATE users
SET `roles` = TRIM(BOTH ',' FROM CONCAT_WS(
    ',',
    NULLIF(`roles`, ''),
    IF(FIND_IN_SET('admin', IFNULL(`roles`, '')) = 0, 'admin', NULL),
    IF(FIND_IN_SET('management', IFNULL(`roles`, '')) = 0, 'management', NULL),
    IF(FIND_IN_SET('user', IFNULL(`roles`, '')) = 0, 'user', NULL)
))
WHERE status = 'active'
  AND (username = '20059616' OR name = '姜海洋');

SELECT id, username, name, department, job_position, `roles`, status
FROM users
WHERE status = 'active'
  AND (
    username = '20059616'
    OR FIND_IN_SET('admin', IFNULL(`roles`, '')) > 0
    OR FIND_IN_SET('management', IFNULL(`roles`, '')) > 0
    OR FIND_IN_SET('super_admin', IFNULL(`roles`, '')) > 0
  )
ORDER BY FIELD(username, 'zzw', '20461992', '20461982', '20059616') DESC, username;
