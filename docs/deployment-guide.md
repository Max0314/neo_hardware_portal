# 硬件门户部署指导

更新时间：2026-08-05

面向在 NeoFlow 平台上部署与运维硬件研发部门户的人。凭据不写在本文，位置见
[凭据](#凭据) 一节。

---

## 一、平台硬性要求

违反其中任何一条都可能被平台管理员回退，也会让服务在迁移或重建后不可用。

| # | 要求 | 本项目如何满足 |
| --- | --- | --- |
| 1 | **禁止在服务器上编辑代码** | 本地改 → `git push` → 服务器 `git fetch` + `checkout` → `deploy.sh` |
| 2 | **禁止在主应用服务器上跑数据库** | Compose 中不含任何数据库服务，统一连 NeoFlowData |
| 3 | **禁止用本地文件存储业务数据** | 文件存储需接入阿里云 OSS（当前为过渡期，见 [OSS](#五文件存储与-oss)） |
| 4 | **只能使用分配给自己的端口段** | 本项目端口段 **39020-39029**，网关占用 **39020** |
| 5 | **只能通过 `~/.nginx/*.conf` 配置反代** | 只写 `location` 等下层指令，禁止 `server{}`／`http{}`／`events{}` |
| 6 | **数据库端口不得暴露公网** | 数据库仅内网 `172.16.0.244`，无公网入口 |
| 7 | **`.env` 权限 600，不进 Git** | 仓库只提交 `.env.example` |

---

## 二、拓扑

```
                         ┌─────────────────────────────────────────┐
  本地开发机 (Windows)    │  GitHub                                 │
  D:\code_CPL\           │  git@github.com:Max0314/                │
  neo_hardware_portal    │  neo_hardware_portal.git                │
        │  git push  ───▶ │                                         │
        │                └──────────────┬──────────────────────────┘
        │                               │ git fetch / checkout
        │ ssh -p 39999                  ▼
        │        ┌──────────────────────────────────────────────────────┐
        └───────▶│  NeoFlow 主应用服务器                                 │
                 │  公网 47.108.48.50   内网 172.16.0.243                │
                 │  域名 neoflow-cn.neo-net.com                          │
                 │  Ubuntu 22.04 / Docker 29.6.2 / Compose v5.3.1        │
                 │                                                      │
                 │  ┌────────────────────────────────────────────────┐  │
                 │  │ 平台 Nginx（root 维护，443 终止 TLS）           │  │
                 │  │   include /home/*/.nginx/*.conf                 │  │
                 │  │   location ^~ /neo_hardware/                    │  │
                 │  │        └─▶ http://127.0.0.1:39020/              │  │
                 │  └────────────────────┬───────────────────────────┘  │
                 │                       │                              │
                 │  ┌────────────────────▼───────────────────────────┐  │
                 │  │ 硬件门户 Docker 栈（用户 max 维护）             │  │
                 │  │   gateway      nginx:alpine   39020:80          │  │
                 │  │     ├─▶ htmlsystm     expose 8000               │  │
                 │  │     ├─▶ neo-backend   expose 8000               │  │
                 │  │     └─▶ neo-web       expose 80                 │  │
                 │  │   本栈内无任何数据库容器                        │  │
                 │  └────────────────────┬───────────────────────────┘  │
                 └───────────────────────┼──────────────────────────────┘
                                         │ 内网 3306
                                         ▼
                 ┌──────────────────────────────────────────────────────┐
                 │  NeoFlowData 数据服务器  172.16.0.244（无公网）        │
                 │    MySQL 8.4.10   →  库 neo_hardware                  │
                 │    PostgreSQL 16  →  本项目未使用                     │
                 │    Redis          →  本项目未使用                     │
                 └──────────────────────────────────────────────────────┘

                 ┌──────────────────────────────────────────────────────┐
                 │  阿里云 OSS（待申请，找陈龙）                          │
                 │    公告正文 / 上传文件 / 聊天附件 / 知识库             │
                 └──────────────────────────────────────────────────────┘

  ── 迁移后仍在运行的旧环境 ──────────────────────────────────────────
                 ┌──────────────────────────────────────────────────────┐
                 │  AWS 52.76.165.169  neoflow.neo-net.com               │
                 │    /neo_hardware/ → 301 重定向到新地址（保留一周）     │
                 │    bi_center：常驻不迁，调用新地址的导出接口           │
                 └──────────────────────────────────────────────────────┘
```

---

## 三、服务器与访问

### 3.1 NeoFlow 主应用服务器

| 项 | 值 |
| --- | --- |
| 公网 IP | `47.108.48.50` |
| 内网 IP | `172.16.0.243` |
| 域名 | `neoflow-cn.neo-net.com` |
| SSH 端口 | **39999**（不是 22） |
| 登录用户 | `max` |
| 认证方式 | **仅密钥**，不支持密码 |
| 系统 | Ubuntu 22.04.5 LTS |
| Docker | 29.6.2，Compose v5.3.1 |
| 用户组 | `max`、`docker`、`deployers` |
| sudo 权限 | 仅 `nginx -t` 与 `systemctl reload nginx`（免密），其余无 |
| 数据盘 | `/home` 196G |

```bash
ssh -p 39999 -i "<密钥路径>" -o IdentitiesOnly=yes max@47.108.48.50
```

建议写入 `~/.ssh/config` 简化：

```
Host neoflow
    HostName 47.108.48.50
    Port 39999
    User max
    IdentityFile <密钥路径>
    IdentitiesOnly yes
```

之后 `ssh neoflow` 即可。

### 3.2 NeoFlowData 数据服务器

无公网入口，只能从主服务器访问，或经主服务器跳板 SSH：

```bash
ssh -J max@47.108.48.50:39999 <user>@172.16.0.244
```

| 服务 | 监听 | 本项目使用 |
| --- | --- | --- |
| MySQL | `172.16.0.244:3306` | ✅ 库 `neo_hardware` |
| PostgreSQL | `172.16.0.244:5432` | ❌ |
| Redis | `172.16.0.244:6379` | ❌ |

主服务器上已装 `mysql` / `mysqldump` 客户端，可直接连：

```bash
# 密码走环境变量，避免出现在 ps 输出和 shell 历史里
MYSQL_PWD='<密码>' mysql -h 172.16.0.244 -P 3306 -u neo_hardware -D neo_hardware
```

> 平台文档提到的 `mysql-admin` / `psql-admin` 包装命令在本机并不存在，直接用 `mysql` 即可。

### 3.3 旧服务器（AWS，迁移后保留一周）

| 项 | 值 |
| --- | --- |
| IP | `52.76.165.169` |
| SSH 端口 | **39999** |
| 用户 | `ubuntu` |
| 项目路径 | `/home/AI/CPL/neo_hardware_portal/neo_hardware_portal` |
| sudo | 免密全权 |

---

## 四、数据库

### 4.1 账号与库

| 项 | 值 |
| --- | --- |
| 库名 | `neo_hardware` |
| 字符集 | `utf8mb4` / `utf8mb4_unicode_ci` |
| 应用账号 | `neo_hardware`@`172.16.0.243` |
| 权限 | 仅 `neo_hardware.*` 的 SELECT/INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/INDEX/REFERENCES/CREATE TEMPORARY TABLES/LOCK TABLES |
| 管理账号 | `neoflow`，准超级用户，**仅用于建库建号，不得用于跑应用** |

应用账号保留 DDL 权限是因为启动时会自建表（`ensure_tables()`），但作用域被限制在自己的库内，
没有 `SUPER`、`FILE`、`GRANT OPTION`，也没有 `*.*` 上的任何实权。

按平台惯例，每个应用一个专用账号（PostgreSQL 上 `ai_super_pm` 服务即如此）。

### 4.2 建库建号（仅首次）

```sql
CREATE DATABASE neo_hardware DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'neo_hardware'@'172.16.0.243' IDENTIFIED BY '<密码>';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX,
      REFERENCES, CREATE TEMPORARY TABLES, LOCK TABLES
  ON neo_hardware.* TO 'neo_hardware'@'172.16.0.243';
FLUSH PRIVILEGES;
```

### 4.3 版本兼容性

旧库 MySQL 8.0.46 → 新库 8.4.10 已做过完整试导入验证，**无损**：19 张表行数、
JSON 字节长度、内容 MD5、列定义 MD5、索引数全部一致，中文无乱码。唯一告警
`Integer display width is deprecated`（1 个 `int(N)` 列）仅为提示，8.4 仍兼容且未重写该列。

### 4.4 备份与恢复

```bash
# 备份（一致性快照，InnoDB 不加锁，不影响线上）
MYSQL_PWD='<密码>' mysqldump --default-character-set=utf8mb4 \
  --single-transaction --no-tablespaces --set-gtid-purged=OFF \
  -h 172.16.0.244 -u neo_hardware neo_hardware | gzip > backup-$(date +%Y%m%d-%H%M%S).sql.gz

# 恢复
gunzip -c backup-xxx.sql.gz | MYSQL_PWD='<密码>' mysql --default-character-set=utf8mb4 \
  -h 172.16.0.244 -u neo_hardware neo_hardware
```

---

## 五、文件存储与 OSS

平台要求文件存储型服务必须接 OSS。当前状态与过渡方案：

| 阶段 | 状态 |
| --- | --- |
| 现状 | 应用仍用本地 Docker 卷；**全仓没有任何代码读取 `STORAGE_BACKEND`**，存储抽象层尚未实现 |
| 过渡 | 第一阶段迁移仍带卷上线，`STORAGE_BACKEND=local` |
| 目标 | 向陈龙申请 OSS → 实现存储抽象层 → `STORAGE_BACKEND=oss` → 迁移对象 → 退役本地卷 |

涉及的三个卷：

| 卷 | 内容 | 去向 |
| --- | --- | --- |
| `htmlsystm_data` | 公告正文、元数据、历史版本 | OSS |
| `htmlsystm_uploads` | 上传文件 | OSS |
| `ai_chatroom_data` | 聊天附件、知识库 | OSS |

⚠️ `ai_chatroom_data` 内的 `chatroom.db`、`dashboard_metrics.db` 是 **SQLite 状态库，不是文件**，
必须迁入 MySQL，**不能上传到 OSS**。

OSS 接入的详细关卡见 [oss-migration-plan.md](./oss-migration-plan.md)。

---

## 六、Nginx 反代

平台 Nginx 在 `server{}` 内 `include /home/*/.nginx/*.conf`，因此用户配置**只能写 `location`
等下层指令**。写 `server{}`／`http{}`／`events{}` 会让全局 `nginx -t` 失败，影响所有人的服务。

`~/.nginx/neo-hardware.conf`：

```nginx
location = /neo_hardware {
    return 301 /neo_hardware/;
}

location ^~ /neo_hardware/ {
    proxy_pass http://127.0.0.1:39020/;

    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Prefix /neo_hardware;

    # WebSocket
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;
    proxy_connect_timeout 60s;

    proxy_buffering off;
    proxy_request_buffering off;
    client_max_body_size 100m;

    proxy_cookie_path / /neo_hardware/;
}
```

`proxy_pass` 结尾的 `/` 会剥掉 `/neo_hardware` 前缀再转发，应用侧靠 `PUBLIC_PATH_PREFIX`
和 `X-Forwarded-Prefix` 生成正确的链接。

生效（`max` 有这两条命令的免密 sudo，不必等管理员）：

```bash
sudo nginx -t && sudo systemctl reload nginx
```

> `nginx -t` 检查的是**全局**配置。若报错先确认是不是自己这份文件的问题，未通过时**不要** reload。

访问地址：`https://neoflow-cn.neo-net.com/neo_hardware/`

---

## 七、部署

### 7.1 首次部署

```bash
ssh -p 39999 -i "<密钥路径>" -o IdentitiesOnly=yes max@47.108.48.50

mkdir -p ~/apps && cd ~/apps
git clone git@github.com:Max0314/neo_hardware_portal.git
cd neo_hardware_portal

cp .env.example .env
chmod 600 .env
vi .env                      # 按 7.3 填写

bash migration/deploy.sh
```

### 7.2 日常更新（务必遵守：本地改代码，服务器只拉取）

```bash
# 本地
git add -A && git commit && git push

# 服务器
cd ~/apps/neo_hardware_portal
git fetch origin <branch> && git checkout <branch> && git pull
bash migration/deploy.sh              # 加 --no-build 可跳过重建镜像
```

### 7.3 `.env` 必填项

值见 [凭据](#凭据)。**此文件权限必须 600，且不得进入 Git。**

| 键 | 说明 |
| --- | --- |
| `COMPOSE_PROJECT_NAME` | Compose 项目名，决定卷名前缀 |
| `TZ` | `Asia/Shanghai` |
| `GATEWAY_PUBLISH_PORT` | **39020** |
| `PUBLIC_BASE_URL` | `https://neoflow-cn.neo-net.com/neo_hardware` |
| `PUBLIC_PATH_PREFIX` | `/neo_hardware` |
| `NEO_PATH_PREFIX` | `/neo_hardware/neo` |
| `MYSQL_HOST` | `172.16.0.244` |
| `MYSQL_PORT` | `3306` |
| `MYSQL_DATABASE` | `neo_hardware` |
| `MYSQL_USER` | `neo_hardware` |
| `MYSQL_PASSWORD` | 见凭据文件 |
| `NEO_INTERNAL_SECRET` | 服务间内部鉴权密钥 |
| `SUPER_ADMIN_USERNAME` | 超级管理员用户名 |
| `AUTH_SESSION_SECRET` | 会话签名密钥 |
| `BI_EXPORT_API_KEY` | BI 导出接口的 `X-API-Key` |
| `DINGTALK_CLIENT_SECRET` | 钉钉应用密钥 |
| `YIDA_SYSTEM_TOKEN` | 宜搭系统令牌 |
| `YIDA_QUERY_USER_ID` | 宜搭取数身份，**必填**，需对全部物料表单有数据权限 |
| `YIDA_LIBRARY_PASSWORD` | 物料库默认密码 |
| `YIDA_MATERIAL_FORMS` | 物料表单白名单 JSON（72 条） |
| `MATERIAL_DB_GLOBAL_PASSWORD` | 物料库全局密码 |
| `ARK_API_KEY` / `TOKENPLAN_API_KEY` / `TOKENPLAN_BASE_URL` | AI 能力配置 |
| `STORAGE_BACKEND` | 过渡期为 `local`，OSS 就绪后改 `oss` |

安全默认值（保持关闭直到明确需要）：

| 键 | 默认 | 含义 |
| --- | --- | --- |
| `YIDA_AUTO_DISCOVER_MATERIAL_FORMS` | `0` | 自动发现表单，仅诊断用 |
| `YIDA_SYNC_SCHEDULER_ENABLED` | `0` | 每日 3 点自动同步 |
| `YIDA_MIN_ROW_RETAIN_RATIO` | `0.5` | 行数跌破该比例拒绝覆盖 |
| `YIDA_ROW_REDUCTION_MIN_BASELINE` | `20` | 减量保护的最小基线行数 |

### 7.4 健康检查

```bash
docker compose ps                                        # 容器状态
curl -s http://127.0.0.1:39020/api/health                # 网关直连
curl -s http://127.0.0.1:39020/api/health?db=1           # 含数据库
curl -sI https://neoflow-cn.neo-net.com/neo_hardware/    # 经平台 Nginx
bash migration/check-stack.sh                            # 全栈验收
```

### 7.5 回滚

```bash
cd ~/apps/neo_hardware_portal
git checkout <上一个可用提交或分支>
bash migration/deploy.sh
```

数据库回滚见 4.4。

---

## 八、对外接口

BI 中心（部署在 AWS 旧服务器，不迁移）通过以下接口取数：

| 接口 | 说明 |
| --- | --- |
| `GET /api/export/usage/monthly?month=YYYY-MM&page=1&pageSize=200` | 月度用量 |
| `GET /api/export/usage/latest` | 最新用量 |

- 鉴权：请求头 `X-API-Key`，值为 `BI_EXPORT_API_KEY`；缺失返回 401
- 数据源：`neo_feature_uses`、`neo_point_events`、`neo_bom_info_snapshots`、
  `neo_user_point_balances`，并关联 `users` 表回填姓名／部门／工号
- **迁移时 `users` 表必须与 `neo_*` 一起迁**，否则 BI 侧这三个字段全空
- 迁移后需把 bi_center 的 `HARDWARE_BI_BASE_URL` 改为新地址。**不要依赖 301 重定向**：
  跨域名跳转时部分 HTTP 客户端会丢弃 `X-API-Key` 这类自定义头
- 当前实现只接受**单个** API Key，无法平滑轮换；换密钥时两侧须同时更新

---

## 九、凭据

**不写在本文，也不进入 Git。** 依据：本仓库 [AGENTS.md](../AGENTS.md) 规定密码按敏感信息处理，
NeoFlow 平台文档亦要求数据库密码不写入共享文档。

| 凭据 | 存放位置 |
| --- | --- |
| SSH 私钥（新服务器） | 本机 `D:\id_ed25519_max` |
| SSH 私钥（旧服务器） | 本机 `D:\amazon-2024.pem` |
| 数据库密码、各类 API Key | 本机 `D:\code_CPL\neo_hardware_portal-secrets\部署与运维完整手册.md` |
| 运行时实际取值 | 服务器 `~/apps/neo_hardware_portal/.env`（权限 600） |

私钥权限应尽量收紧，且不得提交到任何仓库。

---

## 十、常见问题

| 现象 | 排查 |
| --- | --- |
| SSH `Connection closed by remote host` | 端口写成 22 了，应为 **39999**；也可能来源 IP 不在白名单 |
| MySQL `Access denied` | 确认用户名、来源 IP（账号限定 `172.16.0.243`）；管理操作用 `neoflow`，应用用 `neo_hardware` |
| 页面 404 / 静态资源加载不出 | `PUBLIC_PATH_PREFIX` 与 Nginx 的 `X-Forwarded-Prefix` 是否一致 |
| 网关 502 | 后端容器未起或未 healthy，`docker compose ps` 确认 |
| 宜搭同步返回 400 | 未配置 `YIDA_MATERIAL_FORMS` 白名单，这是刻意的安全默认值 |
| 宜搭同步「未读到任何实例」 | `YIDA_QUERY_USER_ID` 对应账号缺少该表单的数据权限 |
| 宜搭同步「物料代码字段全部为空」 | 宜搭源表该列没填，属源数据问题 |
| `deploy.sh` 报 compose 失败 | 先看 `log/deploy.log`；日志路径不可写时会自动回退到项目内 |

---

## 相关文档

- [migration-status-and-requirements.md](./migration-status-and-requirements.md) — 迁移进度与待办
- [oss-migration-plan.md](./oss-migration-plan.md) — OSS 接入关卡
- [architecture.md](./architecture.md) — 系统架构
- [git-workflow.md](./git-workflow.md) — 分支与提交规范
- [AGENTS.md](../AGENTS.md) — AI 协作与工程约束
