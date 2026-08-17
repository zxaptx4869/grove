## 1. 变更工件与基线

- [x] 1.1 运行 `openspec validate --all --strict`，确认本 change 四个工件校验通过
- [x] 1.2 确认当前分支为 `codex/add-create-node-and-archive`，工作区无无关改动

## 2. 后端数据模型与迁移

- [x] 2.1 为 `Candidate` 增加 `new_node_name`、`new_node_parent_id`、`new_node_reason` 三个可空字段
- [x] 2.2 生成 Alembic 迁移，仅新增上述可空列
- [x] 2.3 运行 `cd backend && .venv/bin/alembic upgrade head`，确认迁移可执行

## 3. 后端新节点建议生成

- [x] 3.1 扩展 `NodeRecommendationDraft` 与 `ROUTING_SYSTEM_PROMPT`，仅允许 `no_suitable` 输出新节点建议
- [x] 3.2 在 `_apply_recommendation` 中校验并保存新节点建议，非法父节点按根节点处理
- [x] 3.3 在 `clear_candidate_routing` 中一并清理旧的新节点建议
- [x] 3.4 更新离线路由：无节点时保持 `no_suitable`，不输出虚假建议

## 4. 后端原子归档接口与服务

- [x] 4.1 新增 `NewNodeArchiveRequest` schema 与 `POST /api/candidates/{candidate_id}/archive-with-new-node` 路由
- [x] 4.2 实现 `archive_candidate_with_new_node`：校验候选、父节点，复用或创建同名同父节点
- [x] 4.3 仅创建真实节点时调用 `schedule_refresh`，并复用现有 `archive_candidate` 完成 Entry/证据/候选确认
- [x] 4.4 接口在服务返回后单次 `commit`，任何异常在提交前抛出并回滚

## 5. 后端测试

- [x] 5.1 新增归档测试：新增节点并归档成功，Entry 指向新节点且证据保留
- [x] 5.2 新增复用测试：同项目同父节点同名时复用已有节点，不创建重复节点
- [x] 5.3 新增校验测试：非法父节点返回 400，且不留下节点或 Entry
- [x] 5.4 新增路由测试：`no_suitable` 新节点建议落库，非法父节点被降级
- [x] 5.5 运行 `cd backend && .venv/bin/pytest -q`
- [x] 5.6 运行 `cd backend && .venv/bin/ruff check .`

## 6. 前端 API 与类型

- [x] 6.1 为 `CandidatePayload` 增加 `new_node_suggestion` 类型与解析字段
- [x] 6.2 新增 `archiveCandidateWithNewNode` 客户端函数
- [x] 6.3 在 `queryKeys` 中补充目录树/候选失效键（如需），确保变更查询可被覆盖

## 7. 前端 ReviewPage 交互

- [x] 7.1 在 `routing_status === 'no_suitable'` 时渲染“新增节点并归档”表单，预填建议名称、父节点与理由
- [x] 7.2 保留现有节点下拉与“跳过”，支持改为最接近节点或暂存未归档
- [x] 7.3 当建议路径已有同名同父节点时，解析为已有节点并支持直接采纳，不重复展示“新增”
- [x] 7.4 同一 Source 内按父节点加归一化名称聚合新节点建议，展示涉及候选数量
- [x] 7.5 使用 `useGroveMutation`，显式失效 `sourceCandidates`、`reviewSources`、`projectTree`

## 8. 前端测试与构建

- [x] 8.1 更新或新增 `ReviewPage` 测试：覆盖 `no_suitable` 展示、建议聚合与归档调用
- [x] 8.2 运行 `cd frontend && npm run test:run`
- [x] 8.3 运行 `cd frontend && npm run build`

## 9. 收尾

- [x] 9.1 再次运行 `openspec validate --all --strict`
- [x] 9.2 运行 `openspec archive add-create-node-and-archive`
- [x] 9.3 检查 `git status` 后本地中文 Conventional Commit，不 push、不 merge，等待用户确认
