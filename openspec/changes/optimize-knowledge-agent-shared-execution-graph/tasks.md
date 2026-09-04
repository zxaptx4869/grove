## 1. 图领域骨架、配置与迁移

- [x] 1.1 增加 `SharedExecutionGraph v1`、冻结预算、闭合节点类型、消费者映射、`NodeOutcome` 与节点终态 Pydantic 模型；限制节点、依赖、参数、结果和错误字段长度，历史未知字段直接拒绝。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py -k 'schema or closed or bounds' && .venv/bin/ruff check app/services/knowledge_agent tests/test_knowledge_agent_shared_execution_graph.py`
- [x] 1.2 增加共享图独立特性开关及节点数、深度、单节点依赖、并发度、图/state 字节和总执行预算配置；默认关闭并在 `.env.example` 提供占位值，测试环境隔离开发 `.env`。验收：`cd backend && .venv/bin/pytest -q tests/test_config.py -k shared_execution_graph && .venv/bin/ruff check app/core/config.py tests/test_config.py`
- [x] 1.3 以追加 Alembic 迁移为 Knowledge Agent Run 增加可空 `shared_execution_graph_json` 与 `shared_execution_state_json`，不回填旧 Run，兼容 SQLite/MySQL 8。验收：`cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head && .venv/bin/pytest -q tests/test_migrations.py -k shared_execution_graph`
- [x] 1.4 增加 graph/state 严格序列化、字节校验与恢复入口；旧 Run 空字段、超限、schema 损坏及 plan digest 不匹配分别按规格处理。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py -k 'serialize or restore or corrupt or digest'`
- [x] 1.5 完成图领域骨架、配置和迁移的本地提交。验收：`git diff --check && git status --short`

## 2. 服务端图编译、精确去重与校验

- [x] 2.1 实现从已规范化 `CompositeAnswerPlan v1` 到领域节点的纯函数编译：retrieval 形成 semantic set → content → Evidence，structured request 形成 entry-set 与 count/group/list 输出；保存 original request/requirement 消费者映射。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py -k 'compile or retrieval or structured or consumer'`
- [x] 2.2 实现绑定节点/工具版本、规范化参数、上游、Run 范围指纹、完整性合同和冻结预算的 canonical key/fingerprint；requirement/request id 不进入等价业务参数。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py -k 'canonical or fingerprint'`
- [x] 2.3 合并完全等价的数据集和输出节点，并保留全部合法消费者；相似文本、不同过滤/排序/预算/范围和不能证明合同一致的跨路径语义集合保持独立。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py -k 'deduplicate or equivalent or distinct'`
- [x] 2.4 实现图硬校验：唯一性、闭合节点参数、依赖存在与方向、无自依赖/无环、消费者合法、节点数/深度/入度/工具总调用/对象/Evidence/桶/字节预算；拒绝任何模型或客户端图控制字段。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py -k 'validation or cycle or dependency or budget or unauthorized'`
- [x] 2.5 在任何节点前持久化首次合法图与冻结预算；图编译/校验/首次持久化失败记录独立 server fallback，且仅在没有节点结果时允许进入现有串行执行器。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_shared_execution_graph.py -k 'graph and (persist or fallback or before_execution)'`
- [x] 2.6 完成图编译与校验的本地提交。验收：`cd backend && .venv/bin/ruff check app tests && git diff --check`

## 3. 节点执行、兼容物化与完整性

- [x] 3.1 为各闭合节点实现执行适配器，复用现有语义检索、Entry 读取、Evidence 核验、B1 `EntrySetSpec`、`query_entries` 与 `aggregate_entries`；范围只从 Run 注入，不再次调用任何 planner。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py tests/test_knowledge_agent_structured_query.py -k 'node_executor or dispatcher or scope'`
- [x] 3.2 让共享 entry-set 结果服务多个输出，aggregate 仍直接查询逻辑完整集合，不从 entries limit 反推；semantic/top-k/截断/异常继续产生 limited/unknown。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py -k 'shared_set or aggregate or completeness'`
- [x] 3.3 生成与节点 fingerprint 和输出槽绑定的稳定 result handle；同一共享节点只产生一份工具事实，requirement 关联由合法消费者映射派生。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py -k 'result_handle or tool_fact or consumer'`
- [x] 3.4 实现 graph state 到现有 `CompositeAnswerExecutionSnapshot` 的确定性物化器，按原始 request 聚合 Entry/Evidence/result handles、状态、完整性和错误；兼容综合器无需识别内部图。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py tests/test_knowledge_agent_composite_answer.py -k 'materialize or compatibility or coverage'`
- [x] 3.5 比较同一固化计划的串行与共享图输出，确认 Evidence、精确/limited 语义、tool fact、逐项覆盖、answer basis 和最终状态等价，重复底层调用数减少。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph_eval.py -k equivalence`
- [x] 3.6 完成节点执行与兼容物化的本地提交。验收：`cd backend && .venv/bin/ruff check app tests && git diff --check`

## 4. 确定性调度、安全并行与恢复

- [x] 4.1 实现 Kahn 拓扑 ready 波次、稳定 node id 准入和依赖状态传播；上游失败只阻止后继，其他独立分支继续。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py -k 'topological or ready or upstream_failure'`
- [x] 4.2 在每个波次启动前按稳定顺序预分配工具、Entry、Evidence、桶和耗时额度；同波次完成先后不得改变谁获得预算。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py -k 'quota or deterministic_budget'`
- [x] 4.3 为并行白名单节点使用独立 `AsyncSession` 与不可变 Run 工具上下文，限制并发度；Evidence、Run、审计、检查点和最终物化继续由协调器串行写入。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py -k 'parallel or isolated_session or coordinator'`
- [x] 4.4 每个节点终态后保存按 node id 稳定排序的有界检查点；`completed/empty/limited/partial/failed` 恢复均复用，只重放没有已提交结果的节点。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_worker.py tests/test_knowledge_agent_shared_execution_graph.py -k 'graph and (checkpoint or recovery or terminal)'`
- [x] 4.5 在节点启动、结果接纳、检查点与终态前检查取消；取消停止新节点，独立会话迟到结果不得写入 state、Evidence、成功审计或正常回答。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_worker.py tests/test_knowledge_agent_shared_execution_graph.py -k 'graph and cancel'`
- [x] 4.6 确保持久化图 Run 在开关关闭或配置变化后仍按冻结图恢复；非法图/state 显式失败，已有节点结果后的运行错误不得整体回退串行重跑。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_worker.py tests/test_knowledge_agent_shared_execution_graph.py -k 'graph and (flag_change or corrupt or no_replay)'`
- [x] 4.7 完成调度、并行与恢复的本地提交。验收：`cd backend && .venv/bin/ruff check app tests && git diff --check`

## 5. Runner 接入、可观测与安全门禁

- [x] 5.1 在 quick 复合回答执行边界接入共享图开关：新 Run 可使用共享图，关闭时完全沿用串行路径；investigate、entries、旧 quick 和规划失败兼容路径不变。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_investigation_runner.py tests/test_knowledge_agent_structured_entry_search.py -k 'shared_graph or investigate or entries or feature_flag'`
- [x] 5.2 让并行节点 outcome 由协调器顺序写入模型/工具审计，记录实际 provider/model/status/fallback/error/duration/usage、node fingerprint、消费者数与 reused；共享节点不伪造多次调用，失败不从 fallback 摘要消失。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph.py tests/test_knowledge_agent_runner.py -k 'observability or audit or fallback_summary'`
- [x] 5.3 增加安全硬门禁：跨 Workspace/项目/Run 结果复用为零，Candidate/Draft/Extraction 不进入节点输入，图控制字段/未知节点/写操作被拒绝，查询与统计不推进事实工作集。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph_eval.py -k guardrail`
- [x] 5.4 保持 Run、消息页和原生端公开协议不暴露 graph、query、fingerprint、Entry/Source 全文、授权参数或隐藏推理；旧 Run 与缺少新字段的旧服务端继续兼容。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_api.py tests/test_knowledge_agent_conversations.py -k 'shared_graph or legacy' && cd ../mobile && npm test -- --runInBand src/knowledge-agent/api.test.ts src/knowledge-agent/adapters/answer.test.ts`
- [x] 5.5 完成 Runner、可观测与安全边界的本地提交。验收：`cd backend && .venv/bin/ruff check app tests && cd ../mobile && npm run typecheck && npm run lint && git diff --check`

## 6. 评估、验收与收尾

- [x] 6.1 建立共享执行图评估夹具，覆盖重复 retrieval、同集合 count/group/list、多义务共享 Evidence、相似但不等价查询、上游失败、并发分支和串行/图等价；用底层实际调用次数断言复用，不以易波动墙钟时间作为唯一门槛。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph_eval.py`
- [x] 6.2 完成恢复与并发压力测试：节点完成后崩溃、partial/failed 终态、波次中取消、迟到结果、预算竞争、配置/开关变化、图/state 损坏和重复提交。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_worker.py tests/test_knowledge_agent_shared_execution_graph.py -k 'recovery or parallel or budget or cancel or corrupt or idempotent'`
- [ ] 6.3 启动后端并用 curl 验证 Conversation、提交、Run、历史和可观测端点返回预期 401/200；记录共享前后实际调用次数、结果等价、节点失败、fallback、取消与恢复的脱敏摘要。验收：写入 `docs/验收记录/optimize-knowledge-agent-shared-execution-graph-curl.md`
- [ ] 6.4 运行原生端全量自动化测试、typecheck 与 lint；向用户提供无需新 UI 的真机兼容走查清单，至少覆盖复合解释 + Grove + 统计、Citation/partial/fallback 和历史恢复，由用户执行并反馈。验收：`cd mobile && npm test -- --runInBand && npm run typecheck && npm run lint`，反馈记录写入对应验收文档
- [ ] 6.5 更新 Knowledge Agent 产品形态与迭代记录中的已归档状态和共享执行图阶段进度，只记录本 change 实际完成能力；覆盖补查、B2 多轮循环与 Operation Plan 继续保持后续。验收：`openspec validate --all --strict`
- [ ] 6.6 完成后端全量 pytest、Ruff、迁移往返、原生端全量验证、`git diff --check` 与 OpenSpec 全量严格校验。验收：`cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head && .venv/bin/pytest -q && .venv/bin/ruff check . && cd ../mobile && npm test -- --runInBand && npm run typecheck && npm run lint && cd .. && git diff --check && openspec validate --all --strict`
- [ ] 6.7 按 AGENTS.md 检查遗留问题并先向用户说明背景、原因与影响；仅在用户同意后登记到 `docs/discussions/Grove后续优化清单.md`。验收：`git status --short`
- [ ] 6.8 完成规划/实现各阶段本地提交；用户手动验收通过后再归档、同步主规格并等待用户明确确认推送与合并。验收：`openspec status --change optimize-knowledge-agent-shared-execution-graph && git log --oneline --decorate -8 && git status --short`
