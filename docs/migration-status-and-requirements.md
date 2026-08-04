# 迁移现状与所需条件

本文基于 2026-08-04 对生产主机的只读盘点，不含任何凭据。所有"已核实"条目均来自实际命令输出，
"需取得"条目是我无权限或无法自行确定、必须由你或管理员提供的。

## 前提更正：服务已经在 NeoFlow 上

此前记录的"硬件门户未部署到 NeoFlow、需要整机迁移"与实际不符。实测：

| 检查项 | 结果 |
| --- | --- |
| 公网入口 | `https://neoflow.neo-net.com/neo_hardware/` → HTTP 302（跳登录，正常） |
| 健康检查 | `https://neoflow.neo-net.com/neo_hardware/api/health` → HTTP 200 |
| BI 导出接口 | `/neo_hardware/api/export/usage/latest` 无密钥 → HTTP 401（鉴权正常） |
| 宿主 Nginx | `/etc/nginx/sites-enabled/neoflow.neo-net.com.conf` 已启用（软链） |
| NeoFlow 本体 | `/home/AI/Neoflow/`、`/opt/neo-flow-backend/` 跑在**同一台主机** |

**结论：不存在"跨服务器搬迁"。** 服务器、发布路径、Nginx、SSO 入口、BI 对接都已就位。
剩下的只有两件事：

1. Compose 内置的 `stack-mysql` → 主机共享 MySQL
2. 四个本地 Docker 卷 → 对象存储

---

## 1. 服务器与访问方式

### 已核实

| 项 | 值 |
| --- | --- |
| 主机 | `52.76.165.169`，SSH 端口 `39999`，用户 `ubuntu` |
| 密钥 | `D:/amazon-2024.pem`（已配置在 `~/.ssh/config`，`Host 52.76.165.169`） |
| 内网主机名 | `ip-172-31-38-67` |
| 系统 | Ubuntu 24.04.3 LTS |
| Docker | 29.2.0 |
| 项目路径 | `/home/AI/CPL/neo_hardware_portal/neo_hardware_portal` |
| 磁盘 | 193G 总量，已用 134G（70%），剩余 60G |
| 权限 | `ubuntu` 可管理 Docker，具备免密 sudo |

### 约束（必须遵守）

- **不在服务器上改代码**。只在本地修改 → push → 服务器 `git fetch` + `checkout` → `deploy.sh`。
- `.env` 只存在于服务器，权限 600，不进 Git。修改前先备份。
- 部署脚本日志默认写 `/var/log/docker-stack-deploy.log`（仅 root 可写），非 root 部署时会自动
  回退到 `${ROOT}/log/deploy.log`（见 task-011）。

### 需取得

- [ ] **主机 MySQL 的连接凭据**。主机上有独立于容器的 mysqld 服务（systemd `mysql` active，
      监听 `0.0.0.0:3306`），这应当就是共享数据库。我无凭据，`sudo mysql` 返回
      `Access denied`，未做任何猜测尝试。需要：地址、端口、**专用数据库名**、**最小权限应用账号**。
- [ ] **对象存储的归属与凭据**。主机上有 `docker_minio_data` 卷（2.6GB）和一个 MinIO 容器，
      但该容器属于 `neoflow_ai_pm_release` 项目且已停止 7 天。需要明确：用阿里云 OSS 还是复用
      MinIO；Bucket/Endpoint/Region/前缀；RAM 角色或 STS 授权方式。
- [ ] **共享 MySQL 与对象存储的建库/建桶授权**（谁来建、是否允许本项目自建）。

---

## 2. 旧数据：位置、体量、连接方式

### MySQL（容器 `stack-mysql`，mysql:8.0）

| 项 | 值 |
| --- | --- |
| 库名 | `htmlsystm` |
| 体积 | **29.2 MB**，19 张表 |
| 卷 | `docker_mysql_data`，2.0G（多为 InnoDB 日志与预分配，非业务数据） |
| 暴露 | 仅容器内 `3306/tcp`，**未映射到宿主端口** |

主要业务表：

| 表 | 行数 | 说明 |
| --- | --- | --- |
| `material_db_audit` | 9,703 | 物料库审计 |
| `material_db_libraries` | 58 | 物料库（26 MB，含当前表与历史版本 JSON） |
| `users` | 93 | **BI 依赖，必须与 `neo_*` 一起迁**，漏迁会让姓名/部门/工号为空 |
| `neo_feature_uses` | 485 | BI 数据源 |
| `auth_session_index` | 418 | 登录会话索引 |
| `neo_point_events` | 305 | BI 数据源 |
| `neo_bom_info_snapshots` | 126 | BI 数据源 |
| `neo_user_point_balances` | 17 | BI 数据源 |

其余：`login_attempts`、`audit_logs`、`primary_boards`、`sub_boards`、`material_db_settings`、
`sessions`、`ip_blacklist`、`captcha_tokens`、`neo_points_pending`、`system_config`、`todos`。

### 数据卷（文件）

| 卷 | 实际占用 | 文件数 | 内容 | 迁移目标 |
| --- | --- | --- | --- | --- |
| `docker_htmlsystm_data` | 185.7 MB | 300 | 公告正文、元数据、历史版本 | 对象存储 |
| `docker_htmlsystm_uploads` | 4 KB | **0** | 上传文件（当前为空） | 对象存储 |
| `docker_ai_chatroom_data` | 192.9 MB | 355 | 聊天附件、知识库、**SQLite** | 见下 |
| `docker_mysql_data` | 2.0 GB | 201 | 数据库文件 | **不迁对象存储**，走逻辑导出 |

**`ai_chatroom_data` 内不是所有东西都能上对象存储**：`chatroom.db`、`dashboard_metrics.db` 是
SQLite 状态库（[main.py:76](../neo_ai_chatroom/backend/main.py:76)、[:78](../neo_ai_chatroom/backend/main.py:78)），
必须迁进共享 MySQL，不能当成文件搬走。

### 连接方式

```bash
ssh 52.76.165.169                                  # 已配置别名，含端口与密钥
docker exec stack-mysql sh -c 'mysql -u root -p"$MYSQL_ROOT_PASSWORD" htmlsystm'
docker run --rm -v docker_htmlsystm_data:/d alpine:3.20 sh -c 'ls /d'
```

### 需取得

- [ ] 停写窗口时间（做最终增量同步与切换）
- [ ] 旧数据保留策略（回滚点保留多久、何时授权清理）

---

## 3. 与其他服务的交互

### 已核实：BI 中心（同主机容器 `bi_center`）

**对接已经是活的**，不是待建：

| 配置项 | 值 |
| --- | --- |
| `HARDWARE_BI_ENABLED` | `true` |
| `HARDWARE_BI_BASE_URL` | `https://neoflow.neo-net.com/neo_hardware` |
| `HARDWARE_BI_API_KEY` | 已配置 |
| `HARDWARE_BI_PAGE_SIZE` | `200` |
| `HARDWARE_BI_TIMEOUT` / `VERIFY_SSL` | `15` / `true` |

接口（[bi_export_api.py](../htmlsystm/server/bi_export_api.py)）：

- `GET /api/export/usage/monthly?month=YYYY-MM&page=1&pageSize=200`
- `GET /api/export/usage/latest`
- 鉴权：`X-API-Key`；未带密钥实测返回 401

**迁移约束**：契约不变、后端原子替换。BI 保持原 URL 无感知即可，但

- 所有 `neo_*` 表**和 `users` 表**必须一起迁；
- 当前实现只接受**单个** API Key，无法平滑轮换。要么切换瞬间同步更新两边，要么先加"双密钥并存"能力。

### 已核实：请求链路

```
浏览器 → https://neoflow.neo-net.com/neo_hardware/
       → 宿主 Nginx (sites-enabled/neoflow.neo-net.com.conf)
       → proxy_pass https://127.0.0.1:7892/     ← 带结尾斜杠，剥掉 /neo_hardware 前缀
       → stack-gateway (容器内 443)
       → htmlsystm:8000 / neo-backend:8000 / neo-web:80
```

宿主 Nginx 已设置 `X-Forwarded-Prefix: /neo_hardware` 与 `proxy_cookie_path / /neo_hardware/`。
项目侧对应 `PUBLIC_PATH_PREFIX=/neo_hardware`。**迁移中不要动这段**——它已经工作正常。

### 已核实：同主机其他服务

`bi_center`、`sop-web`、`ai_patents_app`、`ai-code-review-*`、`ai_security_management-*`、
`ai-motion-analysis`、`neocoderinsight`、`neotest-*` 等十余个容器共用这台主机。**清理 Docker
构建缓存、重启主机 Nginx、动 3306 都会波及它们**，任何此类操作都要单独确认。

### 需取得

- [ ] BI 侧的拉取频率与对账口径（谁来验收数据一致）
- [ ] 是否需要在切换前实现"双 API Key 并存"

---

## 4. 剩余步骤

### 第 0 段 · 事故收尾（差最后一步）

- [ ] 生成 72 张表的 `YIDA_MATERIAL_FORMS` 白名单草案 → 人工核对 → 写入 `.env`
- [ ] 跑一次完整同步，核对实例数达到 2,872（分页修复前只有 2,360）
- [ ] 复核 5 张受截断影响表单的物料行数相应上升
- [ ] 决定是否重开 `YIDA_SYNC_SCHEDULER_ENABLED`

业务侧（我做不了）：`线材物料优选库` 源表补物料代码；确认 `CPU&WIFI芯片` 是否本该有数据；
轮换 `MYSQL_PASSWORD` 并停止部署脚本明文打印。

### 第 1 段 · 代码改造（不依赖新资源，现在就能做）

按依赖关系排序：

1. **修知识库相对路径**——[main.py:1585/1588/1789/1790](../neo_ai_chatroom/backend/main.py:1585)
   与 [knowledge_base.py:183](../neo_ai_chatroom/backend/models/knowledge_base.py:183) 绕开了
   `CHATROOM_DATA_DIR`，持久化位置不一致。**这是迁移前必须先修的数据完整性问题。**
2. **修备份脚本**——[backup-all.sh:70](../scripts/backup-all.sh:70) 仍存 `.env` 明文快照。
3. **实现存储抽象层**——目前**零代码**，全仓没有任何应用代码读 `STORAGE_BACKEND`。需要覆盖
   上传、下载、移动、删除、知识库、回收站，并支持"OSS 写入 + 本地回退读取"的双读灰度。
   **这是工作量最大的一块。**
4. **SQLite → MySQL**——`chatroom.db`、`dashboard_metrics.db` 需按模型写专用迁移。
5. **Compose 外部化 MySQL**——移除 `mysql` 服务与 `depends_on`，`MYSQL_HOST` 改从 `.env` 读
   （现写死为 `mysql`，见 [docker-compose.yml:53](../docker-compose.yml:53)、[:128](../docker-compose.yml:128)），
   应用侧改为连接失败重试。
6. **BI 契约测试**——固化两个接口的请求参数、响应字段、错误码，作为切换前后的对账依据。
7. **改运维脚本**——**20 个脚本**写死 `stack-mysql` / 本地卷 / `docker compose exec mysql`，
   迁移后全部失效：`migration/` 下的 `deploy.sh`、`check-db-config.sh`、`check-stack.sh`、
   `emergency-recover.sh`、`reset-mysql-password.sh`、`stack-startup.sh`、`lib-compose-core.sh`、
   `lib-deploy-wait.sh` 等。

### 第 2 段 · 数据迁移与切流（需第 1 段完成 + 新资源到位）

1. **源端盘点**——本文第 2 节已完成大部分；切换前再做一次增量确认。
2. **目标准备**——共享 MySQL 建专用库与最小权限账号；对象存储建桶/前缀、生命周期、访问策略。
3. **测试迁移**——MySQL 逻辑导出 → 校验和 → 恢复到测试库；文件生成清单 + SHA-256 → 传测试前缀；
   用改造后的应用连测试库与测试前缀，验证登录、公告、附件、知识库、BI 两个接口。
4. **正式切换**——停写窗口 → 最终导出与增量同步 → 恢复到正式库/正式前缀 → 切 `.env` 与容器 →
   本机健康检查通过后才对外。**Nginx 那段不用动。**
5. **验收与回滚窗口**——核对表行数、关键业务记录、对象数量与校验和、HTTPS 与 BI 对账。
   旧库与旧卷保留为只读回滚点，未经明确授权不删除。

---

## 汇总：现在卡在哪

| 阻塞项 | 谁来解 |
| --- | --- |
| 主机 MySQL 的库名、账号、密码 | 管理员 |
| 对象存储选型（阿里云 OSS 还是复用 MinIO）与凭据 | 你/管理员 |
| 停写窗口与数据保留策略 | 你 |
| BI 验收口径、是否需要双密钥 | 你 + BI 负责人 |

**第 1 段的 7 项代码改造不依赖以上任何一项，可以立即开始。**
