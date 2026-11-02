# Task 015：原理图 AI 审核长请求稳定性

## Goal

修复原理图 AI 审核在 NeoFlow 迁移后长时间停留在“正在思考”、连接中断后仍继续续写，以及未映射模型被选为默认模型的问题。

## Scope

- 服务：`neo_ai_chatroom` 后端与前端。
- 后端：兼容 NeoFlow `delta.reasoning`，原理图审核关闭思考模式，限制 Token Plan 超时与重试，节流流式推送，去除当前消息的重复上下文。
- 前端：WebSocket 心跳、超时/断线/模型错误终止自动续写、错误状态展示。
- 配置：NeoFlow 模式只展示已有映射的 Token Plan 模型。
- 不修改 NeoFlow 的供应商自动路由策略，请求仍不传 `provider`。

## Verification

- [x] Python 编译检查
- [x] 后端单元测试（26 passed）
- [x] 前端生产构建与 TypeScript 检查
- [x] NeoFlow 部署及健康检查（2026-11-02 补充核验运行版本 `5a44806`，4 个服务 healthy）
- [x] 生产 Token Plan 流式冒烟测试（2026-11-02 隔离合成 WebSocket 业务验证，DeepSeek V4 Pro 返回完整评审 JSON，MySQL/OSS 保存读取及清理通过；详见 [Task 013](task-013-neoflow-tokenplan-models.md#2026-11-02-默认模型切换与业务验收)）

## Git

- 分支：`fix/task-015-schematic-ai-review-stability`
- 主分支：`main`

## Deploy

- 服务器：NeoFlow 应用服务器
- 路径：`~/apps/neo_hardware_portal`
- 部署入口：`bash migration/deploy.sh`

## Notes

- `deepseek-v4-flash` 在 NeoFlow 当前模型目录中没有映射，NeoFlow 模式下从原理图默认模型选项中隐藏；可在上游模型就绪后通过显式 `NEOFLOW_MODEL_bailian_deepseekv4flash` 恢复。
- 回滚：回退本任务合并提交后重新执行标准部署脚本。

## 2026-11-02 浏览器端到端验收补充

- 分支：`codex/schematic-report-e2e-20261102`。
- 使用 Chrome 中现存真实账号会话，经正式门户进入原理图审核，不替换服务端鉴权。网表使用明确标记的合成数据 `CODEX_E2E_20261102_01a199e2`。
- 实际复现：DeepSeek V4 Pro 两轮回复使用 `interface_name`；前端只识别 `type/name`，将 7 个接口归入同一组，并使 U5/U2V 的同名检查互相覆盖，原始 13 项检查只展示 12 项。
- 修复：前端合并、去重键、续写上下文和报告明细统一识别 `type`、`name`、`interface_name`，跳过空名称；保留既有字段优先级和同一接口同一检查的更新规则。只修复前端解析，不改模型、生产提示词、接口、数据库或历史记录。
- 定向验证：`node scripts/test-schematic-review.cjs` 3 项通过，覆盖不同接口同名检查保留、跨轮次同接口更新、旧字段和未合并历史展示。将两轮真实回复重放到修复前后实现，结果由 1 组/12 项恢复为 7 组/13 项。
- 构建验证：`VITE_NEO_PATH_PREFIX=/neo_hardware/neo npm run build` 通过（包含 TypeScript）；保留既有产物体积、Browserslist 与静态资源提示，未扩展至无关优化。
- 部署：修复提交 `dcd315f2` 已推送 GitHub `main` 和任务分支，服务器同步后在共享构建锁内仅构建 web，再运行 `bash migration/deploy.sh --no-build`。web 镜像为 `sha256:d88babb51a6f3a7a89029534685199e5033f87a94db817b019062def9c35f213`，backend 镜像仍为 `sha256:6e108534d4b3b22b1eb33dd1b970ab6a29e4649f5cd350c689314749849e5bc5`，四个服务 healthy。
- 真实登录及页面复验：在独立浏览器会话完成钉钉登录、选择既有企业并返回正式门户，页面确认真实用户身份。正式 Chrome 页面重新提交合成网表，DeepSeek V4 Pro 返回 4 个接口、8 项检查；部署后的页面全部正确分组，8 项处理意见均设为“待定”。未修改模型设置或生产提示词。
- PDF 工具阻塞：已点击“导出评审结果（PDF）”，但检查原生打印窗口时，Computer Use 因无法可靠识别浏览器 URL 自动停止。没有继续操作该窗口，也没有使用其他工具代替打印。服务器只读核对显示两份合成结果均无导出历史，积分事件仍未超过验收前的 ID 560；本机下载目录、桌面及本地验收目录未发现本轮 PDF。不能将点击按钮或页面截图视为文件保存、报告内容或版式验收通过。
- 服务器收尾（2026-11-02 09:57，服务器本地时间）：精确清理两组会话及 6 条消息、功能使用事件 `1159`，以及两份网表的本地缓存和 OSS 对象。目标 result ID 为 `99169c4a-f1b4-4d49-9156-f2987733604f`、`e2dfc8f8-974f-49a2-96e2-a5c6a8b8bacb`；conversation ID 为 `41401bb2-f0e9-4be1-aad9-da2947da10a4`、`22e9b64e-5976-4839-9b6b-c185ad718702`。按会话、分组和消息引用核对关联记忆与抽取去重记录均为零，无积分需要冲销。
- 清理验证：事务内及提交后比较非目标记录指纹，原有消息、会话、35 条评审历史、记忆、功能使用、积分事件及 27 份积分余额均保持一致；登录会话身份记录未变。其他 495 份网表缓存内容及 OSS 对象键集合保持一致，目标残留为零。未注销用户原 Chrome 会话，也未修改其他登录会话。
- 证据：服务器运维目录 `.codex-ops/model-switch-20261102/` 下的 `portal-e2e-web-build.log`、`portal-e2e-deploy.log`、`portal_e2e_cleanup.py`、`portal-e2e-cleanup.json`；本地忽略目录 `.codex/verification/` 保留真实登录、修复前后页面截图及合成回复重放数据。构建产生的未跟踪 vendor 目录因自动审批拒绝删除而保留，未提交、未重试。
- 剩余验收：实际保存 PDF 并逐页检查内容与中文排版、导出后历史回读及浏览器后续聊天流程。原生打印操作仍未完成，若之后由用户恢复该窗口，前端回调可能新增历史或积分，届时需重新核对上述精确范围。当前 Goal 保持未完成，不把工具阻塞记为业务通过。
- 独立普通网页核查：IAB 中已知 `/neo_hardware/neo/bom-check` URL 可正常进入真实登录态页面，面板折叠/展开操作正常；没有触发打印。当前路由仅将聊天组件挂载为原理图和 BOM 模式，BOM 模式明确不渲染聊天区，原理图模式导出前锁定输入且直接调用所选模型。因此没有可独立访问的普通聊天入口用于浏览器默认 `@tokenplan` 验收；后端隔离业务验证不能替代该项。此次未发送聊天、导入文件或产生新增样本。10:00:49 再次只读核对此前合成范围残留仍为零；截图保存于本地 `.codex/verification/ordinary-chat-entry-unavailable.png`。打印阻塞已满足连续三轮 Goal 阻塞审计，状态为 `blocked`；恢复条件为可安全完成的打印/已保存 PDF，以及可用的普通聊天入口或明确纳入范围的入口修复，未擅自新增产品路由。
