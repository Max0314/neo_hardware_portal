# Git 工作流

`neo_hardware_portal` 当前只配置 GitHub remote，因此默认只推 GitHub；后续如新增 GitLab remote，则按总工作区规则一并推送。

## Remote

| remote | 用途 |
| --- | --- |
| `github` | 代码准源：`Max0314/neo_hardware_portal` |

## 默认分支

- 主分支：`main`
- 任务分支：`feature/*`、`fix/*`、`codex/*`。

## 提交前

```bash
git status --short --branch
git remote -v
```

确认没有 `.env`、证书私钥、数据库卷、上传文件、备份包、日志、构建产物或生产导出数据进入暂存区。

## 默认推送

主分支：

```bash
git push github main
```

当前任务分支：

```bash
git push github HEAD
```

如果后续配置 `gitlab-new`，Codex/Claude 完成编码任务后应一并推送 GitLab。

## 部署关系

- Git 推送不等于部署。
- 硬件门户部署、迁移、重启、日志查看和运行验证由 Codex 通过 SSH 到服务器执行。
- 部署前确认服务器 `.env`、证书、数据卷、上传文件和备份不会被 Git 覆盖。

