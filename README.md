# 硬件研发部系统 — Docker 部署

本项目部署在 **NeoFlow 平台**（阿里云），包含管理系统（htmlsystm）、NEO AI 聊天室与内部网关。
数据库在 NeoFlowData（外部 MySQL），文件持久化在阿里云 OSS（本地卷仅作缓存），网关以明文
HTTP 绑定 `127.0.0.1:39020`，TLS 由平台 Nginx 统一终止。详见
[docs/deployment-guide.md](docs/deployment-guide.md)。

## 我该读哪份文档？

| 场景 | 文档 | 是否需离线打包镜像 |
|------|------|-------------------|
| **日常运维**（启停、日志、备份、排障） | [运维手册.md](运维手册.md) | — |
| **新服务器联网部署 + 只导入部分数据**（如公告栏） | [运维手册.md §2](运维手册.md) + [数据迁移指南.md](数据迁移指南.md) | 否，`bash migration/deploy.sh` 现场构建 |
| **整机离线迁机**（原样搬迁代码+镜像+全部数据） | [迁移手册.md](迁移手册.md) | 是，`run-source-migration.sh` |
| **联网整机搬迁**（可 build，数据卷可恢复） | [迁移手册.md](迁移手册.md) 或 deploy + 恢复卷 | 可选 |

## 快速开始（新服务器，可联网）

```bash
cd ~/apps/neo_hardware_portal
cp .env.example .env          # 填写 MYSQL_*、OSS_*、各 API Key（详见 docs/deployment-guide.md）
bash migration/deploy.sh
```

对外访问：`https://neoflow-cn.neo-net.com/neo_hardware/`（登录）与 `.../neo_hardware/neo/`

## 从老环境只迁公告栏

```bash
# 老生产机
./scripts/export-announcements.sh

# 新服务器 deploy 成功后
./scripts/import-announcements.sh /path/to/announce_export_YYYYMMDD
```

详见 [数据迁移指南.md](数据迁移指南.md)。

## 目录结构

| 路径 | 说明 |
|------|------|
| `docker-compose.yml` | 编排入口（5 容器） |
| `.env` / `.env.example` | 环境变量 |
| `migration/` | 部署、迁机、自检脚本 |
| `scripts/` | 备份与数据导出/导入 |
| `运维手册.md` | 日常运维主文档 |
| `迁移手册.md` | 离线整机迁机 |
| `数据迁移指南.md` | 选择性数据迁移 |
