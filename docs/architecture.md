# Architecture

## 服务组成

- `htmlsystm/`：管理系统。
- `neo_ai_chatroom/`：AI 聊天室和相关工具。
- `gateway/`：统一入口和反向代理。
- `migration/`：部署和迁移脚本。
- `scripts/`：备份、导入和运维脚本。

## 数据流

```text
Browser -> gateway -> htmlsystm / neo_ai_chatroom -> database or service data
```

真实运行数据位于数据卷或 `.env` 指定目录，不应进入 Git。
