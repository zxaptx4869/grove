## 1. 数据模型与迁移

- [x] 1.1 `Source` 增加 `recommended_project_id` 与 `project_recommendation_reason`
- [x] 1.2 `Candidate` 增加 `recommended_node_id`、`node_alternatives`、`node_reason`、`routing_status`
- [x] 1.3 新增 Alembic 迁移，为 `sources` 与 `candidates` 增加上述可空列

## 2. Agent 与路由服务

- [x] 2.1 `ExtractionDraft` 增加项目推荐字段；全局来源上下文补充 Workspace 项目列表
- [x] 2.2 新增 `RoutingDraft` 与 Organizing Agent 路由模式（输入项目节点列表）
- [x] 2.3 新增路由服务：读取候选与真实节点、调用路由、校验 `node_id` 后落库
- [x] 2.4 离线 demo 确定性输出：项目推荐为空、节点推荐取项目第一个节点（无节点为 `no_suitable`）

## 3. 触发与处理

- [x] 3.1 项目内来源处理成功后同步路由
- [x] 3.2 全局来源确认/修改项目时触发路由（当前同步实现）
- [x] 3.3 修改项目后清除旧目录推荐并重新路由，不复制候选或 Entry

## 4. API

- [x] 4.1 `SourceOut` 暴露推荐项目字段
- [x] 4.2 `CandidateOut` 暴露目录推荐字段
- [x] 4.3 项目归属修改接口在 `project_id` 变化时触发路由

## 5. 前端

- [x] 5.1 收集箱展示项目推荐并可确认
- [x] 5.2 确认台目录下拉预填推荐节点，并按三档路由状态呈现

## 6. 测试与验证

- [x] 6.1 后端测试：项目推荐、目录推荐、非法节点拒绝、三档状态、路由重跑、Workspace 隔离
- [x] 6.2 前端测试：项目推荐确认、目录预填、三档路由表现
- [x] 6.3 运行 `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`
- [x] 6.4 运行 `cd frontend && npm test -- --run && npm run lint && npm run build`
- [x] 6.5 运行 `openspec validate --all --strict`
