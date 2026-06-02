# AI 工程化说明

本项目是多服务部署栈。AI Agent 修改时要先确认目标服务、部署影响和数据迁移影响。

## 默认流程

1. 阅读 `AGENTS.md` 和当前任务文件。
2. 确认修改属于 `htmlsystm`、`neo_ai_chatroom`、网关、迁移脚本还是文档。
3. 修改最小范围文件。
4. 运行 `make compile`，涉及前端时补充前端验证。
5. 提交并说明部署影响。

## 高风险区域

- `docker-compose.yml`
- `gateway/`
- `htmlsystm/server/`
- `neo_ai_chatroom/backend/`
- `neo_ai_chatroom/src/`
- `migration/`

部署脚本和密码管理逻辑需要额外谨慎。
