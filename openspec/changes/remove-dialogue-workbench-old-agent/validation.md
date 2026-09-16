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

### 初次验证时的待验收状态

- 真实模型的普通问答、搜索后按序号追问、候选稿生成和浏览器刷新后继续会话，仍待用户在已启动的实验台中验收。
- 本轮不声称真实模型语义验收通过；不归档、不推送、不合并。

## 共用核心既有缺陷修复（2026-09-16）

### 与实验台清理的边界

- 会话 `f4bc9a82-a8a7-4f64-9039-9fcb289b0c88` 第 6、7 轮暴露的候选稿误判在 `main` 的同一份 `dialogue_loop/loop.py` 中同样存在，不是移除 old 对照流程引入的回归。
- 本次独立修复只修改 Web 与实验台共用的候选输出校验和相应确定性测试；没有修改实验入口、production adapter、预算、模型、工具、权限、Workspace 或数据库字段。

### 修复与验证

- 将精简候选已有的程序边界补齐机制收敛为普通候选、精简候选和 finalize-only continuation 共用的候选边界；已有同义否定声明不重复，缺失时只追加“尚未写入正式 Entry”声明，不重写候选正文。
- 程序补齐后仍独立扫描正向写入声明；“已经保存/修改/覆盖正式记录”等声称继续被拒绝并保持真实失败状态。
- 使用第 6、7 轮真实输出结构和“我没有改动正式记录”原句制作脱敏夹具。确定性回归覆盖同义否定、缺失补齐、幂等、正向反例、普通候选、精简候选和“继续”无工具收尾。
- dialogue-loop、production adapter 和相关实验台测试：276 项通过。
- `backend/.venv/bin/ruff check`（上述实现与测试范围）：通过。
- `git diff --check`：通过。
- `production_adapter.py` 与实验台 `engine.py` 均继续直接调用共用 `dialogue_loop.run_turn()`，因此 Web 共用路径获得相同修复。
- 未发起真实模型调用；真实语义复测仍待用户执行，不声称已经通过。

## 用户真实会话验收与收尾复核（2026-09-16）

- 用户完成修复后复测并反馈“好像没问题了”，本会话只读核对了实验台持久化记录，未另行发起模型请求。
- 验收会话：`2b47be15-7e7a-47b9-92e4-b3a134a54d4a`；Session：`session-20260916-130250`；模型：`deepseek / deepseek-v4-flash`。
- 7 轮覆盖定义问答、环保等级搜索、第二条正文、补充讨论、候选修改稿、简化候选稿、切换项目查询；全部为 `completed`，无未完成步骤或可继续标记。
- “第二条”通过 `open_list_item` 定位 E0/E1，未重复搜索；候选稿和简化稿通过收尾校验，未再出现“缺少未写入状态”的误判；最后 `list_projects` 返回 4 个项目。
- 环保等级查询达到软阈值后进入 finalizer 并成功完成；未派发的内部请求停止记录不视为本轮失败。
- 候选稿保留未写入与人工采纳说明；本次日志核对不替代对正式库写入的独立数据库审计。
- 本 change 的真实对话路径与候选稿修复场景验收通过。刷新恢复已有确定性测试覆盖，但会话日志不能证明浏览器刷新动作本身，未追加该项人工操作通过的结论。
- 分支相对 `main` 的共用 `loop.py` 差异来自独立修复 `8edd4e8`；实验台清理提交本身不改变核心行为。此前“无核心差异”的结论仅针对清理提交，不能用于描述当前整个分支。
- 保留前述 12 项基线失败说明，不宣称全库测试全部通过。最新回答仍存在简化幅度有限、跨标准排序表述与自身限制说明不一致的内容质量问题；本轮不扩展修复，未擅自写入本地优化清单。
- 当前仅完成验收记录和归档准备，尚未归档、合并或再次推送。
