## 验证复核结果（2026-09-16）

### 范围核对

- `e23813a` 仅修改实验评估入口、报告、相关测试、README 和本 change 工件。相对已含时间字段修复的 `main` 执行 `git diff main HEAD`，没有 `backend/app/`、`backend/evals/dialogue_loop/loop.py` 或移动端文件差异。
- 当前分支的 `e179f3e` 与 `main` 的 `26a97f7` 补丁 ID 相同，只在 `backend/app/services/knowledge_agent/runs.py` 刷新用户消息时间字段；该修复不属于本 change。
- 静态调用核对仍为 `knowledge_agent_worker.py` 调用 `production_adapter.execute_dialogue_loop_run()`，适配器调用 `evals.dialogue_loop.loop.run_turn()`。实验台和实验入口不再导入或调用 `runner.execute_run()`。

### 已通过

- 实验台、dialogue-loop 核心和生产适配确定性测试：268 项通过。覆盖单一统一循环入口、连续对话、按序号追问基础、候选稿路径、刷新后的会话记录恢复、持久化读取、报告导出、取消、隔离和预算。
- `backend/.venv/bin/ruff check backend/evals/dialogue_loop backend/tests/test_knowledge_agent_dialogue_loop.py`：通过。
- `cd frontend && npm run typecheck`：通过。
- `cd frontend && npm run build`：通过，包含 `workbench.html` 产物。
- `cd frontend && npm run test:run -- src/pages/KnowledgeAgentPage.test.tsx`：5 项通过。
- `openspec validate --all --strict`：63 项通过，0 项失败。
- `git diff --check`：通过。
- 真实模式实验台已在 `http://127.0.0.1:8765/workbench` 启动；`/healthz` 返回成功，页面返回 200。启动与健康检查未发送对话，未触发付费模型调用。

### Web Agent 既有失败对照

使用同一虚拟环境，分别在当前分支和从 `main`（`26a97f7`）建立的临时 worktree 中运行完全相同的 Web Agent 测试集合。两边均出现相同的 12 项失败，断言值和错误响应一致，因此没有证据表明它们由本 change 引入：

1. `test_knowledge_agent_worker.py::test_composite_retrieval_exception_records_failed_tool_call`：完整集合中预期 1 条工具调用、实际 3 条；两边单独运行以及紧随 production adapter 测试运行时均通过，属于共享测试数据库下的既有顺序污染。
2. `test_knowledge_agent_api.py::test_structured_answer_with_verified_evidence`：预期 1 条引用、实际 0 条。
3. `test_knowledge_agent_api.py::test_api_conversation_run_and_message_context_fields`：`active_topic_label` 为 `None`。
4. `test_knowledge_agent_api.py::test_api_scope_change_closes_working_set`：`active_context_version_id` 为 `None`。
5. `test_knowledge_agent_api.py::test_api_clarification_run`：`context_decision` 为 `None`，预期 `clarify`。
6. `test_knowledge_agent_entry_revision_api.py::test_revision_submit_and_message_page`：目标知识不在最终引用中，返回 409，预期 201。
7. `test_knowledge_agent_entry_revision_api.py::test_revision_submit_idempotent_201_then_200`：首次提交返回 409，预期 201。
8. `test_knowledge_agent_entry_revision_api.py::test_revision_edit_and_cancel_via_api`：前置提交未生成 `draft`。
9. `test_knowledge_agent_entry_revision_api.py::test_revision_cross_user_404`：前置提交未生成 `draft`。
10. `test_knowledge_agent_entry_revision_api.py::test_revision_confirm_via_api`：前置提交未生成 `draft`。
11. `test_knowledge_agent_entry_revision_api.py::test_revision_undo_via_api_and_cross_user_404`：前置提交未生成 `draft`。
12. `test_knowledge_agent_entry_revision_api.py::test_revision_undo_rejected_after_later_edit_via_api`：前置提交未生成 `draft`。

前述 11 项在干净 pytest 会话中仍于两边同样失败；没有删除、跳过或改写这些涉及正式引用、上下文、候选修订、权限和 Workspace 意图的测试，也没有为使其通过而修改正式 Agent 行为。

### 待人工验收

- 真实模型的普通问答、搜索后按序号追问、候选稿生成和浏览器刷新后继续会话，仍待用户在已启动的实验台中验收。
- 本轮不声称真实模型语义验收通过；不归档、不推送、不合并。
