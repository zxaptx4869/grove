## 1. 后端：版本模型与迁移

- [ ] 1.1 新增 `EntryVersion` 模型（`app/models/entry.py`）：快照字段 + `node_id` + `change_type` + `change_summary` + `version_number`，唯一约束（entry_id, version_number），FK 级联删除
- [ ] 1.2 新增 Alembic 迁移创建 `entry_versions` 表，并为既有 Entry 回填版本 1（当前字段快照，`change_type='created'`，`created_at` 取 Entry 创建时间）

## 2. 后端：版本快照、列表与恢复服务

- [ ] 2.1 `services/entry.py` 增加版本快照 helper（同事务 `flush` 后取 `max(version_number)+1`，保留上限 N=10 滚动丢弃最旧）
- [ ] 2.2 在创建 Entry（归档/新增节点归档）、`edit_entry`（仅实际变化）、`apply_revision_to_entry`、恢复路径接入快照；`add_evidence_to_entry` 不产生版本
- [ ] 2.3 `schemas/entry.py` 增加 `EntryVersionOut` 与 `RestoreRequest`；`ApplyRevisionRequest` 增加可选 `change_summary`
- [ ] 2.4 `api/entry.py` 增加 `GET /api/entries/{id}/versions` 与 `POST /api/entries/{id}/restore`（Workspace 归属校验）

## 3. 后端：AI 修订建议 Agent 与 API

- [ ] 3.1 新增 `agents/revision.py`：结构化草稿与回复输出、系统提示（仅基于 Entry 与来源证据、输出为候选草稿、不引入外部知识）、TestModel/调用失败降级并日志告警
- [ ] 3.2 `schemas/entry.py` 增加生成/调整/应用请求与 `RevisionSuggestionOut`（含 provider/model/is_fallback/error）
- [ ] 3.3 `services/entry.py` 增加修订建议服务：生成、继续调整（全量对话 + 当前草稿）、应用（写 Entry + `ai_revision` 版本 + 上下文刷新）
- [ ] 3.4 `api/entry.py` 增加 `POST /api/entries/{id}/revision-suggestion`、`/refine`、`/apply` 三个端点（Workspace 归属校验）

## 4. 后端测试

- [ ] 4.1 `tests/test_entry.py` 或新测试文件覆盖：创建 v1、编辑追加快照、无变化不追加、候选修订应用带 change_summary、add-evidence 不产生版本、保留上限滚动、恢复（字段+节点）追加恢复版本、越权 404、恢复不存在版本 404
- [ ] 4.2 修订建议测试：未配置模型时降级返回（is_fallback）、生成端点 Workspace 隔离、应用草稿后 Entry 更新并追加 `ai_revision` 版本

## 5. 前端：API 与查询键

- [ ] 5.1 `lib/api.ts` 增加版本与修订建议的类型与函数（fetchEntryVersions / restoreEntryVersion / revisionSuggestion / refineRevisionSuggestion / applyEntryRevisionSuggestion）；`ApplyRevisionPayload` 增加 `change_summary`
- [ ] 5.2 `lib/queryKeys.ts` 增加 `entryVersions`

## 6. 前端：按钮入口与三个面板

- [ ] 6.1 `EntryViews.tsx` 卡片底部操作区与列表操作列增加「编辑 / AI 修订建议 / 版本历史」按钮（沿用「相关知识」风格，列表用紧凑图标 + aria-label）
- [ ] 6.2 新增 `EntryEditDialog`：字段编辑 + 目录选择（复用 `DirectoryTreeSelect`），保存调用 `updateEntry`
- [ ] 6.3 新增 `EntryVersionHistoryDialog`：版本列表 → 查看快照 → 恢复（二次确认）
- [ ] 6.4 新增 `RevisionSuggestionDialog`：一次性对话（消息气泡 + 指令输入）、当前草稿表单（可手改）、生成/继续调整/应用/放弃；降级错误可见
- [ ] 6.5 `ProjectPage` 接线三个回调与面板状态，保存/恢复/应用后失效相关查询并 toast

## 7. 前端测试与静态检查

- [ ] 7.1 `EntryViews.test.tsx` 补充三个按钮渲染与回调测试
- [ ] 7.2 新增/补充面板组件测试：编辑保存、版本列表 + 恢复、修订建议生成与应用（mock API）
- [ ] 7.3 `npm run test:run`、`npm run lint`、`npm run build` 通过；`npm run format` 检查无新增格式问题

## 8. 全量验证与收尾

- [ ] 8.1 后端 `pytest` 全量通过；`ruff check` 无新增问题
- [ ] 8.2 `openspec validate --all --strict` 通过
- [ ] 8.3 归档 `add-entry-version-history-and-revision` 并同步主规格
- [ ] 8.4 本地提交（Conventional Commits 中文信息，按后端/前端/文档分次提交）；不 push、不 merge，等待用户确认
