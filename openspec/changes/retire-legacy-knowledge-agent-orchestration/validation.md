# 验证记录

## 自动化结果

- 实施前在同一环境运行后端全量测试，共 35 项失败：1 项 embedding 回填测试库污染、23 项旧 runner monkeypatch 与当前统一循环不匹配、9 项旧 investigation 执行测试、2 项 runner/shared graph 执行测试。
- 实施后后端全量测试只剩 `tests/test_embedding_retrieval.py::test_backfill_creates_missing_rows` 失败；实施前后均为期望 1 行、实际读到 32 行，证据指向复用测试库的既有状态污染，与本 change 无关。
- 聚焦回归共 485 项，全部通过：`dialogue_loop`、`production_adapter`、Worker、实验台、Candidate、Entry Revision、Web API、历史 Investigation/Run 读取、Evidence、Task State 和保留的 structured-query/read-tool 合同。
- `backend/.venv/bin/ruff check app evals tests` 通过。
- Web `npm run typecheck` 和 `npm run build` 通过；`KnowledgeAgentPage.test.tsx` 5 项通过。
- `git diff --check` 通过。
- `openspec validate --all --strict` 通过，64 项均有效。

## 调用链与恢复边界

- 正式 Web：`/api/knowledge-agent` 创建 Run，Worker 调用 `production_adapter.execute_dialogue_loop_run`，再调用 `evals.dialogue_loop.run_turn`。
- 实验台：`dialogue_workbench.engine` 直接调用同一 `evals.dialogue_loop.run_turn`，不存在 old arm 或 `runner.execute_run` 入口。
- Candidate 与 Entry Revision 继续走各自 operation Run，取消检查统一依赖 `run_control`。
- answer Run 只允许 `claim`、`recovered` 或通过现有安全状态检查的 `dialogue_loop` 快照重试；旧步骤名、空步骤和未知快照明确失败收尾，不转换或进入新循环。

## 保留的兼容代码

- 保留 Run/Conversation schema 中的 `context_decision`、investigation summary、composite/shared graph/coverage repair 快照字段与旧步骤/调用用途常量，用于历史数据读取和序列化。
- 保留 Investigation 表、轮次/查询表、API 详情读取及 `composite_answer_projection`，不再创建或恢复旧执行账本。
- 保留所有 Alembic 历史迁移、数据库字段和历史数据；本 change 无数据库迁移。
- 保留 investigation/composite/shared graph/coverage repair 等旧配置键作为部署配置兼容，当前执行路径无消费者；后续若删除需要独立评估配置合同。
- 保留 `structured_query`、read tools、`task_state`、`dialogue_context`、Candidate、Entry Revision 等现行能力；它们不属于旧 answer 执行器。

## 人工复测清单

1. 在正式 Web 提交普通知识问答，确认状态正常结束且引用可打开。
2. 先搜索获得编号结果，再按序号追问，确认上下文与条目引用未断开。
3. 生成候选稿，确认只生成 Candidate，未经人工确认不写入正式 Entry。
4. 发起 Entry Revision，分别验证预览、拒绝与确认路径，检查 Source 追溯和 Workspace 隔离。
5. 在执行中取消一个 Run，确认轮次收尾为 cancelled，不生成新正式记录。
6. 在运行中刷新页面，确认会话与当前 Run 可恢复显示，已完成轮次不重复执行。
7. 在实验台重复普通问答、搜索后追问、候选稿与刷新恢复，确认单一统一循环体验。

本轮未调用付费真实模型，上述语义与交互验收待人工完成。移动端代码未修改。
