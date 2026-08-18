## 1. 骨架与数据模型

- [x] 1.1 新增 Alembic 迁移，为 `candidates` 增加 `relation_status`、`relation_target_entry_id`、`relation_reason`、`revision_draft` 四个可空列
- [x] 1.2 更新 `Candidate` 模型，补充关系字段与常量（`pending` / `new` / `duplicate` / `supplement` / `conflict`）
- [x] 1.3 更新 `CandidateOut` / `ReviewCandidateOut`，增加关系状态、目标 Entry、理由与修订草稿字段

验收：`cd backend && .venv/bin/alembic upgrade head && .venv/bin/ruff check .`

## 2. 关系判断 Agent 与相似检索

- [x] 2.1 新增 `agents/relation.py`，定义 `EntryRevisionDraft`、`RelationRecommendationDraft`、`RelationDraft` 与 `run_relation_agent`
- [x] 2.2 为关系 Agent 提供离线确定性输出：无 Entry 时全部候选返回 `new`
- [x] 2.3 新增 `services/entry_relation.py`，实现项目内相似 Entry 检索（标题归一化、标题包含、字符 bigram 重叠、top-K）
- [x] 2.4 实现 `route_relations` 与 `clear_candidate_relations`，并应用降级规则（非法 target → `new`，`supplement` 缺草稿 → `duplicate`）

验收：`cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`

## 3. 处理管线接入

- [x] 3.1 在 `OrganizingProcessingProvider.process()` 中于路由成功后调用 `route_relations`
- [x] 3.2 项目内无 Entry 时直接标记候选为 `new`，不调用 AI
- [x] 3.3 用户修改 Source 项目时清除旧关系建议，并在重新路由后重跑关系判断
- [x] 3.4 关系判断失败时记录日志并保持候选 `pending`，不阻塞处理任务完成

验收：`cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`

## 4. 确认动作 API

- [x] 4.1 抽取 `archive_candidate` 中「候选证据转 Entry 证据」逻辑为共享 helper
- [x] 4.2 新增 `POST /api/candidates/{candidate_id}/add-evidence`，补充来源证据并锁定候选
- [x] 4.3 新增 `POST /api/candidates/{candidate_id}/apply-revision`，应用修订草稿并补充来源证据
- [x] 4.4 在候选响应中批量附带目标 Entry 的标题与目录名

验收：`cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`

## 5. 前端展示与交互

- [x] 5.1 扩展 `lib/api.ts` 的候选与修订草稿类型，并增加 `addEvidence`、`applyRevision` 客户端方法
- [x] 5.2 在 `ReviewPage` 按关系状态渲染关系建议面板与对应动作，保留「仍按新知识创建」兜底
- [x] 5.3 在 `BatchReviewView` 的 `routingReason` 优先展示关系信号
- [x] 5.4 补充关系建议与动作的前端测试

验收：`cd frontend && npm run test:run && npm run build`

## 6. 验证与收尾

- [x] 6.1 运行 `openspec validate --all --strict` 确认规格与变更通过校验
- [x] 6.2 运行后端测试与静态检查
- [x] 6.3 运行前端测试与构建
- [ ] 6.4 手动走查确认台与批量视图的重复/补充/冲突分流流程
