# Task 011 宜搭同步空数据覆盖防护

## Goal

阻止宜搭→物料库同步在解析出 0 行或异常减量时覆盖现有物料库，并让同步失败原因可诊断。

事故背景：一次全量同步处理 72 张表，成功 30、失败 42、写入 0 行。那 30 张"成功"实际是把当前
表覆盖成了只有表头的空表——旧代码对空投影仍以 `overwrite=True` 写库。旧数据被压入历史版本，
因此表现为"当前表 0 条、历史表 52 个"。42 个失败来自宜搭表单实例查询接口 `POST
/v1.0/yida/forms/instances/search` 返回 500 `innerError`，具体成因未定论。

## Scope

- 服务：`htmlsystm`（宜搭同步）、`neo_ai_chatroom/systm_tool` 物料库页面
- 文件：
  - `htmlsystm/server/material_yida_projection.py`：写库前行数安全校验、`YidaSyncSafetyError`
  - `htmlsystm/server/yida_config.py`：`YIDA_MATERIAL_FORMS` 白名单解析、安全开关、阈值
  - `htmlsystm/server/material_db_api.py`：触发同步前校验白名单配置
  - `htmlsystm/server/yida_sync_runner.py`：每日定时同步默认关闭
  - `htmlsystm/server/yida_client.py`：恢复 TLS 证书校验、退避加抖动
  - `htmlsystm/scripts/yida_sync_test.py`：写库需 `--write --confirm-write` 双确认
  - `htmlsystm/scripts/yida_probe.py`：stdout UTF-8 兼容
  - `neo_ai_chatroom/systm_tool/material-database.html`：展示全部失败项而非首个截断错误
  - `.env.example`：新增同步安全变量
- 是否涉及部署或迁移：涉及部署；不涉及数据结构迁移。**恢复被清空的 30 个物料库是独立后续动作。**

## 防护规则

1. 投影行数为 0：写库前抛 `YidaSyncSafetyError`，不覆盖、不产生历史版本。
2. 异常减量：原库行数 ≥ `YIDA_ROW_REDUCTION_MIN_BASELINE`（默认 20）且新行数低于原行数的
   `YIDA_MIN_ROW_RETAIN_RATIO`（默认 50%）时拒绝覆盖。
3. 同步源必须来自 `YIDA_MATERIAL_FORMS` JSON 白名单，每项必须同时给出 `form_uuid` 和
   `library_name`。自动发现（`YIDA_AUTO_DISCOVER_MATERIAL_FORMS`）默认关闭，仅供排查。
4. 每日定时同步（`YIDA_SYNC_SCHEDULER_ENABLED`）默认关闭，待白名单和历史数据核验后再开。
5. 单张表失败不影响其余表；被阻断的表计入 `blocked` 并在页面列出完整原因。

## Verification

- [x] 编译检查：`python -m compileall -q htmlsystm neo_ai_chatroom/backend scripts migration`
- [x] 单元测试：`cd htmlsystm && python -m pytest server/tests -q` → 30 passed
      （含空投影不覆盖、异常减量不覆盖、白名单校验、TLS 与退避抖动用例）
- [x] 前端内联脚本语法检查
- [x] Docker/服务器部署验证：2026-08-04 09:25 部署完成，5 个容器 healthy，
      `/api/health?db=1` 返回 `db: true`

## Git

- 分支：`fix/task-011-yida-sync-safety`（基于 `fix/task-010-material-library-dedupe`）
- 提交：见分支历史
- GitHub 同步状态：已推送

## Deploy

- 服务器/路径：`52.76.165.169:39999`（ubuntu）→ `/home/AI/CPL/neo_hardware_portal/neo_hardware_portal`
- 服务/容器：`stack-htmlsystm`、`stack-neo-web`、`stack-neo-backend`、`stack-gateway`
- 部署动作：本地改代码 → push → 服务器 `git fetch` + `checkout` → `bash migration/deploy.sh`
  （服务器上不改代码）
- 运行状态和日志检查：容器日志出现 `宜搭每日定时同步未启用（YIDA_SYNC_SCHEDULER_ENABLED=0）`
  即表示定时同步已停；手动同步返回 400 并说明未配置白名单

### 部署前置修复

首次部署失败于 `migration/deploy.sh` 把日志重定向到只有 root 可写的
`/var/log/docker-stack-deploy.log`，重定向失败导致 compose 未执行却报出
「docker compose up -d --build 失败」。已改为不可写时回退到 `${ROOT}/log/deploy.log`。

### 事故根因（服务器日志证实）

42 个失败全部是 `宜搭接口 500: {"code":"innerError","message":"异常:没有权限"}`；30 个
「成功」的日志是 `实例 0 条 → 物料 0 行`，即宜搭返回空结果集。两者是同一根因：**宜搭侧
授权在 2026-08-01 前后失效**，部分表单直接拒绝，部分表单静默返回空。不是表单类型问题。

`YIDA_QUERY_USER_ID` 未在 `.env` 配置，走 `yida_config.py` 里硬编码的默认 userId。宜搭按
该查询人的权限取数，因此这个账号的权限变动会造成上述现象，是首要排查方向。

### 数据损失盘点（2026-08-04 只读核对）

- 72 个库中 32 个当前表为 0 行；其余 40 个数据完好，停留在 7/31 那次成功同步。
- 30 个可从 `history[0]`（`2026-07-31T03:04`）恢复，合计 1,942 行。
- `CPU&WIFI芯片`、`线材物料优选库` 创建于 2026-06-10，最早的历史版本即为 0 行，**从未有过
  数据**，不是本次事故的受害者，属于源表映射的独立问题。
- `0805电阻(R)` 只有 1 个历史版本（112 行），是唯一副本。
- 清空发生在 8/01 凌晨定时同步；之后几次因 task-010 的去重判定为 `unchanged`，未继续污染历史。

### 恢复结果（2026-08-04 09:35 完成）

30/30 个库恢复成功，1,942 行。SQL 独立复核：72 个库中 70 个非空、合计 3,326 行，仅上述两个
从未有数据的库仍为空；历史版本数仍为 1～53，未删除任何版本；`material_db_audit` 新增 30 条
`restore_from_history` 记录。抽查 `0402电阻(R)` 经应用读取为 266 行，表头与物料代码正常。

## Notes

- 部署风险：`.env` 未配置 `YIDA_MATERIAL_FORMS` 时，同步按钮会返回 400 并说明原因。这是刻意的
  安全默认值，不是回归。
- 回滚方式：回退到本分支之前的提交即可恢复旧行为；但旧行为会重新引入空表覆盖风险。
- 备份：`/home/AI/CPL/backups/material-db-20260804-092010/material_db_libraries.sql.gz`
  （部署前所做，SHA256 已记录）。
- 未完成项：
  1. 宜搭授权需业务侧恢复。首要排查 `yida_config.py` 里硬编码的默认查询人 userId 在宜搭应用
     「硬件协助」中的权限状态。授权恢复前不要开启同步。
  2. 授权恢复后，先用只读预检确认 72 个表单，再配置 `YIDA_MATERIAL_FORMS` 白名单，最后才考虑
     重新打开 `YIDA_SYNC_SCHEDULER_ENABLED`。
  3. `CPU&WIFI芯片`、`线材物料优选库` 从未有过数据，需单独查源表字段映射。
  3. 同步结果仍保存在进程内存，重启即丢失；后续应持久化每张表的同步结果。
  4. **`migration/deploy.sh` 的验收环节会明文打印 `MYSQL_PASSWORD` 到终端和 `log/deploy.log`**，
     该凭据已落盘，需轮换并改掉打印行为。
