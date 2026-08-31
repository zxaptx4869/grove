# 基线核对记录（任务 1.3 / 1.4）

> 日期：2026-08-31；分支：`codex/add-knowledge-agent-structured-entry-search`（85c1978，工作区干净）。

## 前置修复确认（任务 1.2）

三个用户单独处理的审查问题均已合入 main 与本特性分支（本分支正是基于含修复的 main，仅领先一个规划提交）：

| 问题 | 提交 |
|---|---|
| EntryVersion.change_type 在 MySQL 8 下长度不足 | `ef2a29a fix: 迁移扩 entry 版本类型列以兼容 knowledge_agent_revision` |
| Revision Draft edit/cancel 与 confirm 并发竞态 | `80206dc fix: 修订草稿编辑与取消改为状态条件更新防并发覆盖`；配套 `b0679ce fix: Run 取消同步不再覆盖 confirming 修订草稿` |
| Candidate confirm 路由失败 rollback 后访问过期 ORM 对象 | `c484a44 fix: 候选确认路由失败后重读对象避免过期属性触发 MissingGreenlet` |

`main` 与 `origin/main` 同为 `b0679ce`，本分支为 `main + 85c1978`（本次 change 的规划提交）。无需合并、无冲突。

## 测试基线

| 检查项 | 基线结果 |
|---|---|
| `backend/.venv/bin/pytest backend/tests` | 497 passed（43.24s） |
| `backend/.venv/bin/ruff check backend/app backend/tests` | All checks passed |
| `cd mobile && npx jest --runInBand` | 10 suites / 101 tests passed |
| `cd mobile && npm run lint` | 通过，无错误 |
| `cd mobile && npm run typecheck` | 通过，无错误 |
| iOS Expo export | 成功（metadata.json，1.6KB） |
| Android Expo export | 成功（metadata.json，1.9KB） |
| `openspec validate --all --strict` | 49 passed, 0 failed |

## 复用点与兼容边界核对（任务 1.4）

### 后端

- **Run/Message 持久化与提交**：`KnowledgeAgentRun` / `KnowledgeMessage`（`app/models/knowledge_agent.py`）；幂等提交与活动槽在 `app/services/knowledge_agent/runs.py::submit_message`，本次扩展 `request_result_mode` 需要与 `request_context_mode`、`request_answer_mode` 同样固化在创建事务。
- **终态写入**：`runs.py::finalize_run` 目前只接受 `answer`；entries 路径需要同事务写兼容助手摘要 + `actual_result_mode` + `entry_result_json` + fallback summary，不创建输出工作集版本。
- **Run 输出组装**：`runs.py::run_out` 与 `conversations.py::message_out`；`KnowledgeMessagePageOut.runs` 已按去重 Run 集合返回，新增字段后旧客户端缺失字段需兜底。
- **消息分页游标**：`conversations.py::_encode_cursor/_decode_cursor`（base64 `id:` 前缀）只绑定消息 id；结果分页需要新的不透明游标，绑定 run id / owner / workspace / schema / offset，不能复用消息游标语义。
- **混合召回与重排**：`app/services/vector_search.py::hybrid_recall_by_query_with_meta`（确定性关键词 + embedding RRF）、`app/services/knowledge_agent/tools.py::search_confirmed_knowledge`（范围加载、种子合并、`run_semantic_agent` 重排、`_ordered_entries`）；结构化搜索可复用 `_load_scope_entries`、召回与重排，但需要独立的 Entry 装配（摘要、项目、目录、类型、来源数、match hint）而不生成 Evidence/Citation。
- **关键词字段命中**：`vector_search.py::_keyword_hit` 覆盖标题、正文、目录名/描述、来源标题，可作为 `match_hint` 的服务端可解释来源。
- **Entry 详情**：`app/api/entry.py::get_entry` + `entry_out`/`entry_eager_options`，移动端已通过 `knowledgeAgentApi.getEntryCurrent` 复用；结果详情需要按当前 owner+Workspace 重新校验并对比快照 `updated_at`。
- **可观测性**：`observability.py` 的 `StageMeta`/`record_model_invocation`/`record_tool_call`/`run_fallback_summary`；新增 `PURPOSE_RESULT_MODE_ROUTE` 与 `structured_entry_search` 工具摘要沿用同一机制。
- **Worker/恢复/取消**：`knowledge_agent_worker.py::process_one_run` 按 run_kind 分派，`execute_run` 在步骤边界 `_check_cancelled`；entries 分支在 runner 内实现并在终态事务一次性提交。
- **工作集**：`working_set.py` 的 `create_context_version` 只在回答路径调用；entries 路径不调用，即不推进工作集。

### 移动端

- **领域协议**：`mobile/src/knowledge-agent/types.ts`、`api.ts`（snake/camel 归一化）、`queryKeys.ts`、`errors.ts`。
- **状态**：`state/modes.ts`（一次性模式覆盖）、`state/submission.ts`（幂等 client_message_id）、`state/messages.ts`（composeThread / upsertRun 按 id 去重）。
- **控制器**：`hooks/useConversationController.ts`：提交、轮询、Run override、消息归并、范围切换与刷新时清空本地错误/游标。
- **界面**：`ConversationScreen` 的 `ThreadMessage` 分派（answer/draft/revision），`AnswerCard`、`ModeSheet`、`Composer`、`CitationSheet`、`ui.tsx`（Card/Sheet/Badge/AppButton）。
- **兼容边界**：旧响应缺少 `requestResultMode`/`entryResult` 时继续按 answer 渲染 AnswerCard；旧提交请求未带 `result_mode` 时后端按 auto；旧 Run 三个新字段为空按 `auto / answer / 无结果` 读取。

## 明确边界

- 不通过内部 HTTP 复用后端服务；跨服务复用直接调用现有 Python 服务函数。
- 本 change 不新增第三方依赖；复用 PydanticAI / AIProvider / 混合召回 / 原生主题组件。
