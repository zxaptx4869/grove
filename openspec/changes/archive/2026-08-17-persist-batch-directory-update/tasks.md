## 1. 变更工件与基线

- [x] 1.1 运行 `openspec validate --all --strict`
- [x] 1.2 确认分支为 `codex/persist-batch-directory-update`

## 2. 后端

- [x] 2.1 `Candidate` 增加 `user_node_id` 并生成 Alembic 迁移
- [x] 2.2 批量候选列表返回 `user_node_id`
- [x] 2.3 新增批量更新目录接口（校验项目归属与节点归属）
- [x] 2.4 批量确认归档优先使用 `user_node_id`，其次推荐节点
- [x] 2.5 后端测试：更新目录持久化、确认后批量采纳用该节点、未设置回退推荐
- [x] 2.6 运行 `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`

## 3. 前端

- [x] 3.1 API 类型与函数：`user_node_id`、`batchUpdateCandidatesDirectory`
- [x] 3.2 修改目录确认调用持久化接口，成功后清空勾选并失效查询
- [x] 3.3 批量列表按 `user_node_id ?? recommended_node_id` 分组
- [x] 3.4 前端测试更新：确认后请求更新目录接口、勾选清空
- [x] 3.5 运行 `cd frontend && npm run test:run && npm run lint && npm run build`

## 4. 收尾

- [x] 4.1 再次运行 `openspec validate --all --strict`
- [x] 4.2 运行 `openspec archive persist-batch-directory-update`
- [x] 4.3 本地中文 Conventional Commit，不 push、不 merge，等待用户确认
