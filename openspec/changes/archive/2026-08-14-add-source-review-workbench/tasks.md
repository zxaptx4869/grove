## 1. 数据模型与迁移

- [x] 1.1 为 `Source` 增加 `review_status` 字段，新增 Alembic 迁移

## 2. 候选决策服务

- [x] 2.1 实现 Candidate 状态机、编辑、重新打开与 Source 审阅状态派生服务
- [x] 2.2 实现单条决策与 Source 内批量决策 API

## 3. 审阅查询 API

- [x] 3.1 实现项目内待审 Source 查询 API
- [x] 3.2 Source 列表返回审阅状态

## 4. 前端确认台

- [x] 4.1 项目导航新增「确认台」入口
- [x] 4.2 实现确认台页面：待审 Source 抽屉、原始材料、候选列表与操作
- [x] 4.3 实现候选编辑、采纳、拒绝、跳过与 Source 内多选批量决策

## 5. 测试与验证

- [x] 5.1 后端测试：决策状态机、编辑、重新打开、批量、审阅状态派生、Workspace 隔离
- [x] 5.2 前端测试：确认台渲染与候选操作
- [x] 5.3 运行 `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`
- [x] 5.4 运行 `cd frontend && npm test -- --run && npm run lint && npm run build`
- [x] 5.5 运行 `openspec validate --all --strict`
