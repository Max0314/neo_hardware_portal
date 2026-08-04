# Task 012 宜搭查询人配置化与实例分页修复

## Goal

消除 [task-011](./task-011-yida-sync-safety.md) 事故排查中暴露的三个根因级问题：查询人身份被
硬编码、实例分页静默截断、空结果的两种成因无法区分。

## Scope

- 服务：`htmlsystm`（宜搭同步）
- 文件：
  - `htmlsystm/server/yida_client.py`：`_first_not_none`、`total` 解析、翻页终止条件
  - `htmlsystm/server/yida_config.py`：去掉 `query_user_id` 硬编码兜底、补充报错说明
  - `htmlsystm/server/material_yida_projection.py`：空结果按成因分类告警
  - `.env.example`：`YIDA_QUERY_USER_ID` 改为必填并说明选型要求
- 是否涉及部署或迁移：涉及部署；不涉及数据结构迁移。

## 问题与修复

### 1. 查询人硬编码（事故根因）

`yida_config.py` 把某位员工的 userId 写死为默认值，`.env` 未配置时静默使用。宜搭按该账号的
**数据权限**返回实例，因此该员工调离硬件研发部后：42 张表单返回 `没有权限`，30 张返回 0 条
实例，同步在无人察觉的情况下把物料库覆盖成空表。

改为必填环境变量，缺失时 `check_yida_config()` 显式报错并提示应使用专用服务账号。

### 2. 实例分页静默截断（长期存在，与事故无关）

`search_form_instances` 的总数解析写成：

```python
total = (a or b or c) if isinstance(result.get('result'), dict) else None
```

条件表达式优先级最低，整个 `or` 链都落在 `if` 的真分支里。宜搭实际返回
`{currentPage, data, totalCount}`，顶层没有 `result` 键，判断恒为 False，`total` 变成 `None`
后回退成 `len(data)`；`iter_form_instances` 又用 `seen >= total` 提前结束，于是**每张表单只
同步第一页**。

实测：72 张表单共 2,872 条实例，实际只同步到 2,360 条，**静默丢失 512 条（18%）**。

| 表单 | 实际 | 截断后 | 丢失 |
| --- | --- | --- | --- |
| 0402电阻(R) | 321 | 100 | 221 |
| 接插件物料优选表 | 272 | 100 | 172 |
| 0201电阻(R) | 151 | 100 | 51 |
| 轻触开关物料优选表 | 141 | 100 | 41 |
| 0402电容(C) | 127 | 100 | 27 |

修复：用 `_first_not_none` 按序取候选值（`or` 会把合法的总数 0 当成缺失）；翻页只按「本页
未满」结束，不再依赖 `total`；达到 `max_pages` 时告警而非静默停止。

### 3. 空结果成因不可区分

「一条实例都没读到」和「读到实例但物料代码全空」原本共用一句错误信息。前者通常是查询人没有
数据权限，后者是源表没填，排查方向完全相反。现在按 `instance_count` 分别给出提示。

实例：`线材物料优选库` 有 27 条实例但物料代码列全空——这是源表数据缺失，不是权限问题，也不是
字段映射问题（映射 `物料代码 -> numberField_mkmczyp6` 正确）。

## Verification

- [x] 单元测试：`cd htmlsystm && python -m pytest server/tests -q` → 42 passed
      （新增 11 项：总数解析含顶层/嵌套/0 值/缺失、`_first_not_none`、低报 total 时继续翻页、
      不满页结束、达最大页数告警、查询人必填、空结果两种成因分别断言）
- [x] 编译检查：`python -m compileall -q htmlsystm neo_ai_chatroom/backend scripts migration`
- [x] 真实数据验证（只读，未写库；容器内代码已还原并与仓库比对一致）：
      `0402电阻(R)` 321 条、`接插件物料优选表` 272 条、`0201电阻(R)` 151 条，与宜搭返回的
      `totalCount` 一致，修复前均为 100。
- [ ] 服务器部署验证：待执行

## Git

- 分支：`fix/task-012-yida-query-user-and-pagination`（基于 `fix/task-011-yida-sync-safety`）
- 提交：见分支历史
- GitHub 同步状态：待推送

## Deploy

- 服务器/路径：`52.76.165.169:39999`（ubuntu）→ `/home/AI/CPL/neo_hardware_portal/neo_hardware_portal`
- 服务/容器：`stack-htmlsystm`
- 部署动作：本地改代码 → push → 服务器 `git fetch` + `checkout` → `bash migration/deploy.sh`
- **部署前必须先在服务器 `.env` 中配置 `YIDA_QUERY_USER_ID`**，否则同步会返回「未配置」错误。
  应急可用硬件研发部在职人员的 userId；长期应改用专用服务账号。

## Notes

- 部署本身不会触发同步：白名单仍为空、定时同步仍关闭（见 task-011）。
- 分页修复后单次同步的实例量从 2,360 升至 2,872，物料行数会明显上升。task-011 的减量保护只
  拦下降不拦上升，不会误阻断。
- 未完成项：
  1. `YIDA_QUERY_USER_ID` 的取值需业务侧决定；建议申请专用服务账号而非绑定自然人。
  2. `线材物料优选库` 的物料代码列需业务侧在宜搭源表补录。
  3. `CPU&WIFI芯片` 源表 0 条实例，需业务侧确认是否应有数据。
  4. 恢复同步后应复核 5 张受截断影响表单的物料行数是否相应上升。
