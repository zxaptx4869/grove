## 1. 持久化、配置与闭合类型骨架

- [x] 1.1 为 `KnowledgeAgentRun` 追加补查控制、计划、串行执行、共享图和图 state 可空字段，新建 Alembic 迁移并验证 SQLite/MySQL 8 DDL 与旧行兼容。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_models.py tests/test_knowledge_agent_worker.py -k 'coverage_repair or legacy'`
- [x] 1.2 增加默认关闭的补查开关和查询/结构化请求/节点/工具/Entry/Evidence/桶/耗时/计划与快照字节配置，实施数值范围校验。验收：`cd backend && .venv/bin/pytest -q tests/test_config.py -k coverage_repair`
- [x] 1.3 实现 `CoverageRepairBudget/Plan/Snapshot` 闭合 Pydantic 类型、严格字节门禁、稳定序列化和损坏快照拒绝；基线快照能完整往返 answer/coverage/basis/fallback。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py -k 'snapshot or bytes or schema'`
- [x] 1.4 增加补查 Run step/purpose/stop reason 常量，保证旧 Run 与旧客户端投影不反向猜测补查。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_api.py tests/test_knowledge_agent_conversations.py -k 'coverage_repair or legacy'`
- [x] 1.5 完成持久化与类型骨架的本地提交。验收：`cd backend && .venv/bin/ruff check app tests && cd .. && git diff --check`

## 2. 逐项准入、模型候选与服务端规范化

- [x] 2.1 实现基于 coverage status、basis policy、合法句柄与 input completeness 的可修复准入；排除 answered/failed、纯 model_allowed 漏答和当前不可核验 external_required。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py -k eligibility`
- [x] 2.2 实现 `CoverageRepairPlanDraft v1` 与 planner prompt，只接收原始问题、不可变义务、已执行摘要、可修复 id 和冻结预算，只输出有界 retrieval/结构化请求候选。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py -k 'draft or prompt or planner'`
- [x] 2.3 实现服务端规范化：目标必须属于准入集合，依据策略不放宽，结构化请求复用 B1 校验，范围只从 Run 注入，超限或未知/写字段拒绝整份候选。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py -k normalization`
- [x] 2.4 实现与执行器无关的 retrieval/structured canonical signature，拒绝首次已完成或候选内重复请求；全部无新查询时固化 `no_novel_request`。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py -k 'duplicate or canonical or no_novel'`
- [x] 2.5 实现 planner 最多一次调用、provider/model/fallback/error/duration/usage 审计与规划前后取消检查；模型失败保留基线。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py -k 'plan_once or observability or cancel'`
- [x] 2.6 完成准入与规划的本地提交。验收：`cd backend && .venv/bin/ruff check app tests && cd .. && git diff --check`

## 3. 串行/共享图补查、去重与恢复

- [ ] 3.1 实现补查子计划转换和 `RepairRunStorageAdapter`，将执行、graph/state 读写限定到补查字段而不改写首次 plan/execution/graph/state。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py -k 'adapter or immutable_baseline'`
- [ ] 3.2 接入串行补查：只执行新请求，每个请求终态持久化，恢复只重放未提交请求，Entry/Evidence/耗时/字节预算使用冻结值。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py -k 'serial and (execute or recovery or budget)'`
- [ ] 3.3 接入共享补查图：最多八个新节点，使用独立图/state 和冻结预算，继承稳定拓扑、并行会话隔离、协调器顺序审计与迟到结果拒绝。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py tests/test_knowledge_agent_shared_execution_graph.py -k 'repair_graph'`
- [ ] 3.4 固化补查 execution mode；开关/配置变化后仍恢复原串行或图路径，快照非法或指纹不匹配时显式失败，不重规划、改道或重放首次执行。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py tests/test_knowledge_agent_worker.py -k 'flag_change or frozen or corrupt or no_replay'`
- [ ] 3.5 在新请求命中同 Run 已读来源时复用 Evidence 行/句柄，并以实际工具计数断言首次完成节点、重复请求和 Evidence 均未重放。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair_eval.py -k 'reuse or no_duplicate_call'`
- [ ] 3.6 实现首次与补查 execution 稳定合并，拒绝 request/handle 冲突，保留首次输入序列化值并只追加新合法句柄。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py -k merge_execution`
- [ ] 3.7 完成补查执行与恢复的本地提交。验收：`cd backend && .venv/bin/ruff check app tests && cd .. && git diff --check`

## 4. Runner 编排、再综合与诚实失败

- [ ] 4.1 在 quick 复合路径首次综合后持久化基线快照，按准入决定跳过或进入一次补查；开关关闭、investigate、entries、兼容 quick 与规划 fallback 不变。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_coverage_repair.py -k 'runner or feature_flag or unaffected'`
- [ ] 4.2 只在补查产生新合法 Evidence/tool fact 时用合并 execution 再综合，重用现有句柄校验、数字事实、coverage、basis 和 Citation 派生。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py -k 'resynthesis or coverage or basis or citation'`
- [ ] 4.3 实现 coverage 非退化门禁：新回答不能丢失基线 answered 义务；补查 planner/执行/再综合失败时恢复基线 answer/coverage/basis，并显式保留 partial/insufficient/gaps/fallback。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py -k 'baseline_fallback or non_regression or failure'`
- [ ] 4.4 在规划、节点启动/接纳、检查点、再综合和终态前复用取消检查，取消不投影内部基线为正常回答或推进工作集。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_worker.py tests/test_knowledge_agent_coverage_repair.py -k 'repair and cancel'`
- [ ] 4.5 将补查 planner/图/工具/再综合/停止的真实状态写入现有审计与 fallback 汇总，确定性跳过不伪造调用。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py tests/test_knowledge_agent_runner.py -k 'observability or fallback_summary or skipped'`
- [ ] 4.6 保持现有 Run/消息页与原生端只投影 answer/points/Citation/coverage/gaps/basis/fallback 和既有计划摘要，内部补查查询、图、节点、范围与指纹不出现在公开 JSON。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_api.py tests/test_knowledge_agent_conversations.py -k 'coverage_repair or composite or legacy' && cd ../mobile && npm test -- --runInBand src/knowledge-agent/api.test.ts src/knowledge-agent/adapters/answer.test.ts`
- [ ] 4.7 完成 Runner、综合和协议兼容的本地提交。验收：`cd backend && .venv/bin/ruff check app tests && cd ../mobile && npm run typecheck && npm run lint && cd .. && git diff --check`

## 5. 评估、隔离、无写入与压力覆盖

- [ ] 5.1 建立代表性评估夹具：复合解释 + Grove Evidence + 结构化统计，覆盖首次完整跳过、可修复 partial/insufficient、补查改善和补查后仍有缺口。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair_eval.py -k coverage`
- [ ] 5.2 覆盖串行/共享图结果等价、首次节点无重放、候选重复调用拒绝、同 Run Evidence 复用与实际工具调用次数。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair_eval.py -k 'serial_graph_equivalence or call_count or reuse'`
- [ ] 5.3 覆盖 planner 非法/失败、工具部分失败、再综合失败、预算耗尽、无新查询和基线非退化，断言状态、gaps 与 fallback 不伪正常。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair.py tests/test_knowledge_agent_coverage_repair_eval.py -k 'failure or budget or no_novel or non_regression'`
- [ ] 5.4 覆盖取消、每类检查点恢复、配置/开关变化、损坏快照、重复提交和租约重试，断言每 Run 最多一次 planner/补查阶段。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_worker.py tests/test_knowledge_agent_coverage_repair.py -k 'repair and (cancel or recovery or idempotent or corrupt or flag_change)'`
- [ ] 5.5 建立 owner/Workspace/项目/跨 Run 隔离硬门禁，以前后计数验证 Entry、Source、Candidate、Draft/Extraction、目录、Operation 和事实工作集无写入副作用。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_coverage_repair_eval.py -k guardrail`
- [ ] 5.6 完成评估、隔离与无写入门禁的本地提交。验收：`cd backend && .venv/bin/ruff check app tests && cd .. && git diff --check`

## 6. 自动化验收、文档与本地收尾

- [ ] 6.1 更新 `backend/.env.example` 的补查开关与预算占位，在知识 Agent 产品形态与迭代记录中将本阶段记为本地完成待走查，不把 B2、外部搜索或 Operation Plan 写成已实现。验收：`openspec validate --all --strict && git diff --check`
- [ ] 6.2 执行迁移 upgrade/downgrade/upgrade，再启动后端并用 curl 验证 Conversation、提交、Run、取消、历史和可观测端点为预期 401/200，记录串行/图补查、失败保底和无重放的脱敏摘要。验收：写入 `docs/验收记录/add-knowledge-agent-bounded-coverage-repair-curl.md`
- [ ] 6.3 运行后端全量 pytest、Ruff 和迁移往返。验收：`cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head && .venv/bin/pytest -q && .venv/bin/ruff check .`
- [ ] 6.4 运行原生端全量测试、typecheck 与 lint；向用户提供无新 UI 的真机兼容走查清单，覆盖完整回答跳过、缺口改善、剩余 partial/insufficient、Citation、fallback、取消和历史恢复，由用户执行并反馈。验收：`cd mobile && npm test -- --runInBand && npm run typecheck && npm run lint`
- [ ] 6.5 执行 `git diff --check` 与 `openspec validate --all --strict`，核对 tasks 与实际完成项，停留在本地特性分支，不归档、不推送、不合并。验收：`openspec status --change add-knowledge-agent-bounded-coverage-repair && git status --short --branch`
- [ ] 6.6 按 AGENTS.md 检查遗留问题，若有则先向用户说明背景、原因与影响，只在用户同意后登记到 `docs/discussions/Grove后续优化清单.md`。验收：`git status --short`
- [ ] 6.7 完成验收文档与自动化结果的本地提交；等待用户真机验收反馈和后续明确归档/推送/合并授权。验收：`git log --oneline --decorate -8 && git status --short --branch`
