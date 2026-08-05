# 迁移现状与待办清单

更新时间：2026-08-05（迁移已执行完成，见文末「执行结果」）

硬件门户从 AWS 旧服务器迁往阿里云 NeoFlow。本文只记录事实与决策，不含任何凭据。
"已验证"表示有实际命令输出佐证；"待确定"表示需要人拍板，我不能自行假设。

## 迁移范围

```
旧：AWS 52.76.165.169                    新：阿里云 NeoFlow
    neoflow.neo-net.com/neo_hardware/        neoflow-cn.neo-net.com/neo_hardware/
    Compose 内置 stack-mysql             →   NeoFlowData 共享 MySQL 172.16.0.244
    四个本地 Docker 卷                   →   本地卷（第一阶段）→ OSS（第二阶段）
    gateway 自签证书 443                 →   gateway HTTP 39020
```

---

## A. 已确定并实测验证

### 新服务器

| 项 | 值 |
| --- | --- |
| SSH | `ssh -p 39999 -i D:\id_ed25519_max -o IdentitiesOnly=yes max@47.108.48.50` |
| 主机名 / 内网 | `NeoFlow` / `172.16.0.243` |
| 系统 | Ubuntu 22.04.5，Docker 29.6.2，Compose v5.3.1 |
| 磁盘 | `/home` 196G，已用 895M |
| 我的组 | `max`、`docker`、`deployers` |
| sudo 权限 | 仅 `nginx -t` 与 `systemctl reload nginx`（免密） |
| 端口段 | **39020-39029**，实测全部空闲 |

### 数据库

| 项 | 值 |
| --- | --- |
| 地址 | `172.16.0.244`：MySQL 3306 / PostgreSQL 5432 / Redis 6379，实测均可达 |
| MySQL 版本 | **8.4.10**（旧服务器是 8.0，跨大版本） |
| 管理账号 | `neoflow`，准超级用户，群内共享 |
| **应用账号** | **`neo_hardware`@`172.16.0.243`**，库 `neo_hardware`，utf8mb4_unicode_ci |
| 应用账号权限 | 仅 `neo_hardware.*` 的 SELECT/INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/INDEX/REFERENCES/CREATE TEMPORARY TABLES/LOCK TABLES；无 SUPER、无 `*.*` |

专用账号符合平台既有规范：PostgreSQL 上 `ai_super_pm` 服务用的就是同名专用角色与库，
且共享的 `neoflow` 账号连 PG 都连不上（pg_hba 无其条目）。MySQL 侧此前没有任何应用账号，
仅因尚无应用使用 MySQL——本项目是第一个。

### 旧服务器

| 项 | 值 |
| --- | --- |
| SSH | `52.76.165.169:39999`，用户 `ubuntu`，密钥 `D:/amazon-2024.pem` |
| 项目路径 | `/home/AI/CPL/neo_hardware_portal/neo_hardware_portal` |
| nginx | 已格式化并 reload；8 个对外路径冒烟通过 |

`/hr_review/` 返回 502 是既有故障，与本次改动无关：`hr-resouce-analyse-app-1` 已
`Exited (0) 11 days ago`，端口 39090 无监听。

### 待迁数据规模

| 对象 | 体量 |
| --- | --- |
| MySQL `htmlsystm` | **29.2 MB**，19 张表（`mysql_data` 卷 2.0G 绝大部分是 InnoDB 开销） |
| `htmlsystm_data` | 185.7 MB / 300 文件（公告正文、元数据、历史版本） |
| `htmlsystm_uploads` | 4 KB / **0 文件**（当前为空） |
| `ai_chatroom_data` | 192.9 MB / 355 文件（聊天附件、知识库、**两个 SQLite**） |

关键表：`material_db_audit` 9703 行、`material_db_libraries` 58 行（26 MB，含历史版本 JSON）、
`users` 93 行、`neo_feature_uses` 485 行、`neo_point_events` 305 行、`auth_session_index` 418 行。

**`users` 表必须与 `neo_*` 一起迁**，漏迁会让 BI 的姓名、部门、工号全空。

---

## B. 已决定，待执行

| # | 决策 |
| --- | --- |
| 1 | 外部路径沿用 `/neo_hardware`；新域名 `neoflow-cn.neo-net.com`；单域名子路径 |
| 2 | 内部协议改 **HTTP**，gateway 不再跑自签证书（平台 nginx 已终止 TLS） |
| 3 | gateway 对外端口用 **39020** |
| 4 | 库名 `neo_hardware`（原 `htmlsystm`），仅改 `.env` 的 `MYSQL_DATABASE`，代码零改动 |
| 5 | 旧地址做 **301 重定向**；替换块已备好，见 `D:\code_CPL\nginx-backup\cutover-neo_hardware-block.conf` |
| 6 | **bi_center 留在 AWS 不迁**，改它的 `HARDWARE_BI_BASE_URL` 指向新地址；不依赖重定向（301 跨域名可能丢 `X-API-Key`） |
| 7 | OSS 后置：第一阶段仍用本地卷；但**存储抽象层现在就写**，避免 OSS 到位后返工两次 |
| 8 | 报告审核系统跟着迁，但在门户迁完之后；细节另议 |
| 9 | 停机方式：停老服务 → 迁移 → 直接启用新的（原定昨晚，未执行） |
| 10 | 禁止在服务器上编代码：本地改 → push → 服务器 checkout → deploy |

---

## C. 已答复的决策

| # | 事项 | 决定 |
| --- | --- | --- |
| 1 | 停机时机 | 收到迁移指令后先检测旧服务有无人使用，无人使用才停 |
| 2 | 旧服务保留期 | **一周** |
| 3 | BI 切换时机 | **完全部署验证通过后**再改 `HARDWARE_BI_BASE_URL` |
| 4 | 报告审核形态 | 保持**独立 Docker 服务**；门户内只加访问链接；复用门户登录；纳入使用统计 |
| 5 | OSS | 迁移完成后再向陈龙申请 |
| 6 | 宜搭白名单 | 立即收尾，优先级最高 |
| 7 | 线材／CPU&WIFI 空库 | 宜搭源表本就没有数据，不再作为问题追踪 |
| 8 | 旧库 `MYSQL_PASSWORD` 轮换 | 旧库一周后退役，不轮换；但**部署脚本明文打印密码的行为要在迁移前修掉**，否则新服务器会重蹈覆辙 |

第 4 项需要注意：报告审核平台**当前完全没有鉴权**（`app/middleware/` 只有 `rate_limiter.py`，
全仓无 auth/token/cookie 代码），且 `ports` 直接映射宿主 `0.0.0.0:8000`，现在仅靠云安全组
保护。"复用门户登录"与"纳入使用统计"都是新开发，不是配置项。门户侧可复用的机制：
`NEO_INTERNAL_SECRET` 内部鉴权、`_DASHBOARD_FEATURE_LABELS` 用量统计。另立任务处理。

---

## D. 待做的代码工作（不需要决策，只需要时间）

按依赖顺序：

| # | 工作 | 说明 |
| --- | --- | --- |
| 1 | **MySQL 8.0 → 8.4 试导入验证** | 唯一可能爆意外的环节，应最先做 |
| 2 | **知识库相对路径修复** | `main.py:1585/1588/1789/1790` 与 `knowledge_base.py:183` 绕开 `CHATROOM_DATA_DIR`，迁移前必修的数据完整性问题 |
| 3 | **Compose 改造** | 移除 `mysql` 服务与 `depends_on`；`MYSQL_HOST` 从 `.env` 读；gateway 改 HTTP；端口改 39020；应用侧加连接重试 |
| 4 | **存储抽象层** | 目前**零代码**，全仓无任何应用代码读 `STORAGE_BACKEND`。要覆盖上传/下载/移动/删除/知识库/回收站，支持 local 与 oss 双后端 |
| 5 | **SQLite → MySQL** | `chatroom.db`、`dashboard_metrics.db` 需按模型写专用迁移，不能当文件搬 |
| 6 | 备份脚本去掉 `.env` 明文快照 | `scripts/backup-all.sh:70` |
| 7 | 运维脚本去写死项 | **20 个脚本**写死 `stack-mysql`／本地卷／`docker compose exec mysql` |
| 8 | BI 契约测试 | 固化两个导出接口的参数、字段、错误码，作为切换前后对账依据 |

---

## E. 迁移当天的执行顺序

1. 停老服务写入（确认无人使用）
2. `mysqldump` 导出 → 校验 → 导入新库 `neo_hardware`
3. 三个数据卷打包 → 传新服务器 → 校验 SHA-256
4. 新服务器 `.env` 配好 → `deploy.sh` 起容器 → 本机健康检查
5. 写 `~/.nginx/neo-hardware.conf` → `sudo nginx -t` → `sudo systemctl reload nginx`
6. 经 `https://neoflow-cn.neo-net.com/neo_hardware/` 验证登录、公告、物料库、BI 两个接口
7. 改 bi_center 的 `HARDWARE_BI_BASE_URL`，验证 BI 拉数正常
8. 旧服务器 nginx 换成 301 重定向 → `nginx -t` → `reload`
9. 旧服务与旧数据保留为只读回滚点

---

## 执行结果（2026-08-05 19:10–19:35）

迁移已完成。旧服务停机约 25 分钟（19:10 停止应用 → 19:35 新服务对外可用）。

### 验收数据

| 校验项 | 源库 AWS 8.0.46 | 新库 阿里云 8.4.10 |
| --- | --- | --- |
| 表数 | 19 | 19 |
| JSON 字节总长度 | 15,122,772 | 15,122,772 |
| 当前表 JSON MD5 | `66653d74…` | 相同 |
| 历史表 JSON MD5 | `c3181aab…` | 相同 |
| `users` 全表 MD5 | `4297e41d…` | 相同 |
| `material_db_audit` MD5 | `be4e02c3…` | 相同 |

数据卷：`htmlsystm_data` 300 文件、`htmlsystm_uploads` 0 文件、`ai_chatroom_data` 357 文件，
与源端一致。传输全程三段 SHA-256 比对无差异。

### 线上状态

| 项 | 结果 |
| --- | --- |
| 新地址 | `https://neoflow-cn.neo-net.com/neo_hardware/` → 302（跳登录），`/login` 200 |
| 健康检查 | `/api/health` 200，`/api/health?db=1` 返回 `db: true` |
| NEO 聊天室 | `/neo_hardware/neo/` 200 |
| 容器 | gateway / htmlsystm / neo-backend / neo-web 四个 running & healthy |
| 网关 | `127.0.0.1:39020->80`，明文 HTTP，TLS 由平台 Nginx 终止 |
| 数据库 | `172.16.0.244` 库 `neo_hardware`，应用账号 `neo_hardware` |
| 旧地址 | `/neo_hardware/*` → 301 到新域名，路径与查询串完整保留 |
| 同机其他服务 | AWS 与阿里云两侧均未受影响 |

### ⚠️ 跨境 SNI 阻断（迁移中发现的新问题）

从 AWS 访问 `https://neoflow-cn.neo-net.com` 的 TLS 握手在 Client Hello 后被 RST 重置，
实测 5/5 全部失败；而**按 IP 直连并显式设置 Host 头则返回 200**。TCP 443 本身可达，
因此是 SNI 触发的网络层阻断，服务器侧无法解决。

影响：`bi_center` 部署在 AWS，无法直接访问新域名。

**已采取的过渡措施**：旧服务器 Nginx 保留 `location ^~ /neo_hardware/api/export/`，
按 IP 反代到新服务器（nginx 默认不发送 SNI，正好绕开阻断），其余路径照常 301。
BI 侧无需任何改动，实测两个导出接口均返回 200，无密钥仍 401。

**这是临时方案，随旧服务器一周后退役而失效。** 后续须择一：

1. `bi_center` 一并迁到阿里云（最彻底）
2. 由网络/安全侧解除该域名的跨境阻断
3. 在阿里云侧为 BI 提供一个不受 SNI 阻断影响的入口

### 回滚点

- 旧服务器 `stack-mysql` 仍在运行，应用容器已停，数据完整保留
- 完整备份：旧服务器 `/home/AI/CPL/backups/migration-20260805-191511/`（含数据库与三个卷，SHA-256 已记录）
- 旧 Nginx 配置备份：`/etc/nginx/sites-available/neoflow.neo-net.com.conf.bak-redirect-20260805-192601`
  与本机 `D:\code_CPL\nginx-backup\`
- 保留期：**一周（至 2026-08-12）**
