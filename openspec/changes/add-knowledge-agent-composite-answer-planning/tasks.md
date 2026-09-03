## 1. 领域骨架、配置与迁移

- [x] 1.1 增加 `CompositeAnswerPlan v1`、回答义务、检索/结构化输入请求、执行检查点、`CompositeToolFact` 与逐项覆盖领域类型；所有模型可控字段使用闭合枚举、长度与数量限制。验收：`cd backend && .venv/bin/ruff check app/agents app/models/knowledge_agent.py app/schemas/knowledge_agent.py`
- [x] 1.2 增加复合回答特性开关及义务数、检索数、结构化请求数、计划/结果字节、对象/Evidence、执行耗时预算，并在 `.env.example` 提供占位配置；默认关闭且不改变旧路径。验收：`cd backend && .venv/bin/pytest -q tests/test_config.py -k composite_answer && .venv/bin/ruff check app/core/config.py tests/test_config.py`
- [x] 1.3 以追加 Alembic 迁移为 Knowledge Agent Run 增加可空 `composite_answer_plan_json`、`composite_answer_execution_json`、`composite_answer_coverage_json`，不回填或猜测旧 Run；迁移兼容 SQLite/MySQL 8。验收：`cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head && .venv/bin/pytest -q tests/test_migrations.py -k composite_answer`
- [x] 1.4 扩展 Run、消息页和 answer point 输出 schema：只追加可选计划摘要、逐项覆盖、`requirement_ids`，保持旧 `answer`/`points`/`citations`/basis、entries v1/v2 和缺字段历史可读。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_api.py tests/test_knowledge_agent_conversations.py -k 'composite or legacy'`
- [x] 1.5 完成领域骨架、配置和迁移的本地提交。验收：`git diff --check && git status --short`

## 2. 复合规划模型与服务端规范化

- [x] 2.1 实现版本化 composite planner 提示与 Pydantic 输出，同时传入原始消息、`standalone_query`、范围标签、上下文决策及允许的用户消息句柄；提示要求按回答义务归并而非按句子生成工具调用。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_models.py -k composite_answer_plan`
- [x] 2.2 实现计划规范化与硬校验：稳定重编号 requirement/request、校验关联、闭合类型/依据策略/EntrySetSpec/输出及总预算，拒绝范围/对象 id、SQL、未知工具、写操作、空消费者和非法引用。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_composite_answer.py -k 'normalize or validation or budget'`
- [x] 2.3 让结构化 `basis_mode=knowledge_only` 和原始消息中的等价明确限制确定性收紧全部回答义务；“结合我的知识库”允许一般解释使用模型知识但要求相关个人义务实际读取 Grove。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_composite_answer.py -k 'basis or original_message'`
- [x] 2.4 在任何工具执行前持久化服务端规范化计划，并记录独立 purpose、prompt version、provider、model、fallback、error、duration 与 usage；同 `client_message_id` 和 Worker 恢复不得再次规划。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_worker.py -k composite_plan`
- [x] 2.5 规划失败、非法或未配置时显式记录 composite fallback 并进入既有安全 basis/quick 路径；开关关闭时完全保持旧执行。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_composite_answer.py -k 'fallback or feature_flag'`
- [x] 2.6 完成复合规划与校验的本地提交。验收：`cd backend && .venv/bin/ruff check app tests && git diff --check`

## 3. 固定一次受控执行

- [x] 3.1 调整 answer Run 顺序为“上下文 → 结果形态 → 回答模式 → quick 复合计划”，使混合解释/知识/统计自动路由为 answer；显式 entries 继续走 B1，investigate 继续走既有调查图。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_structured_entry_search.py -k 'composite or mixed_result_mode or investigate'`
- [x] 3.2 为每份 `retrieval_request` 复用 `search_confirmed_knowledge → read_entries → read_evidence`，保存 request/requirement/Evidence 关联、真实状态与完整性；范围只从 Run 注入。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_composite_answer.py -k retrieval`
- [x] 3.3 为复合计划中的 `structured_request` 复用 B1 EntrySetSpec 规范化、dispatcher、`query_entries` 与 `aggregate_entries`，不再次调用 structured query planner，不从截断列表反推聚合。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_composite_answer.py tests/test_knowledge_agent_structured_query.py -k 'composite or aggregate'`
- [x] 3.4 按规范化顺序串行执行多份输入请求并实施调用数、对象、Evidence、桶、耗时和 JSON 字节总预算；本 change 不加入跨请求合并、DAG 或并行。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_composite_answer.py -k 'order or multiple or total_budget'`
- [x] 3.5 为输入请求生成同 Run、计划版本和规范化参数绑定的稳定指纹；每个请求后提交有界检查点，恢复复用已完成结果，只重放未完成只读步骤。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_worker.py -k 'composite and (recovery or fingerprint)'`
- [x] 3.6 在规划、各输入请求和终态边界检查取消；迟到结果不得提交，查询执行不得创建或修改 Entry、Source、Candidate、Draft、目录或事实工作集。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_worker.py tests/test_knowledge_agent_composite_answer.py -k 'composite and (cancel or readonly)'`
- [x] 3.7 完成固定执行图的本地提交。验收：`cd backend && .venv/bin/ruff check app tests && git diff --check`

## 4. 工具事实、逐项覆盖与最终综合

- [ ] 4.1 从结构化输出生成服务端 `CompositeToolFact` 与稳定 result handle；complete 纯结构化结果使用精确措辞，semantic/top-k/截断/异常使用 limited/unknown 固定边界。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_composite_answer.py -k tool_fact`
- [ ] 4.2 扩展回答模型上下文与 point 草稿，传入原始消息、规范化义务、合法用户陈述、关联 Evidence、tool facts 和执行缺口；point 绑定 requirement/result handles，正文不得泄漏句柄。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_models.py tests/test_knowledge_agent_evidence.py -k 'composite or requirement'`
- [ ] 4.3 实现逐 point 关联校验和最多一次相同输入的输出重试：拒绝未知/无关 requirement、Evidence/result handle，`grove_only` 无依据内容不得通过，external requirement 不得伪装完成。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_composite_answer.py -k 'coverage or retry or invalid_binding'`
- [ ] 4.4 将 tool fact 作为不可改写的确定性 point 按义务顺序插入，拒绝与精确数值或完整性边界冲突的模型文字，并继续由服务端稳定拼接 answer。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_composite_answer.py tests/test_knowledge_agent_evidence.py -k 'tool_fact or answer_text'`
- [ ] 4.5 从合法 points、Evidence、tool facts、用户消息和模型知识权限派生每项 `answered/partial/insufficient/failed`、现有 coverage/gaps、整体 answer status 与实际 basis；零散 Citation 不得掩盖漏答。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_composite_answer.py -k 'status or basis or omitted'`
- [ ] 4.6 原子提交 answer、实际依据、复合覆盖、Run 终态和活动槽；部分工具失败保留合法内容，不触发第二轮工具规划或整条旧 quick 重跑。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_worker.py -k 'composite and (atomic or partial)'`
- [ ] 4.7 完成综合回答与覆盖校验的本地提交。验收：`cd backend && .venv/bin/ruff check app tests && git diff --check`

## 5. API、历史恢复与原生端兼容

- [ ] 5.1 在 Run 与消息页投影有界计划摘要和逐项覆盖，不返回原始模型计划、完整 prompt/Entry/Source、隐藏推理或授权参数；历史分页和范围切换只读生成时快照。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_api.py tests/test_knowledge_agent_conversations.py -k composite`
- [ ] 5.2 扩展原生端类型与 snake_case 适配以容忍可选 `requirement_ids`、计划摘要和逐项覆盖；旧 Run、旧 points 和旧服务端缺字段继续可读。验收：`cd mobile && npm test -- --runInBand src/knowledge-agent/api.test.ts src/knowledge-agent/adapters/answer.test.ts`
- [ ] 5.3 保持现有回答卡、依据概览、Citation、partial/insufficient/fallback 与 gaps 展示，不暴露内部任务拆解或隐藏思维过程；无需新增顶层结果形态或设置项。验收：`cd mobile && npm test -- --runInBand src/knowledge-agent/components/components.test.tsx -t '复合回答|部分回答|依据'`
- [ ] 5.4 完成 API 与原生兼容的本地提交。验收：`cd backend && .venv/bin/ruff check app tests && cd ../mobile && npm run typecheck && npm run lint && git diff --check`

## 6. 评估、安全与恢复测试

- [ ] 6.1 建立复合回答评估夹具，覆盖单一通用问题、概念 + Grove、概念 + 精确统计、多项共享请求、比较/建议、自然语言 knowledge-only、外部材料和首项漏答；不得按单条问法增加关键词补丁。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_composite_answer_eval.py`
- [ ] 6.2 增加安全硬门禁：跨 Workspace/项目为零、Candidate/Draft/Extraction 不进入输入、范围/对象 id/SQL/未知工具/写操作被拒绝、模型知识不生成伪 Citation、查询不推进事实工作集。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_composite_answer_eval.py -k guardrail`
- [ ] 6.3 覆盖计划/执行/覆盖 JSON 大小上限、重复提交、租约恢复、工具部分失败、回答模型失败、取消与迟到结果，确认 provider/model/fallback 全链路可观测。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_worker.py tests/test_knowledge_agent_composite_answer.py -k 'recovery or fallback or cancel or observability'`
- [ ] 6.4 完成后端全量测试、Ruff 与迁移往返，并提交测试修正。验收：`cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head && .venv/bin/pytest -q && .venv/bin/ruff check .`

## 7. 自动验收、用户走查与收尾

- [ ] 7.1 启动后端后先用 curl 验证 Conversation、提交、Run 查询和消息历史端点返回预期 401/200 而非 404；记录一般解释 + Grove、解释 + 精确统计、limited 统计、knowledge-only、计划非法、fallback、取消和恢复响应。验收：将命令与脱敏响应摘要写入 `docs/验收记录/add-knowledge-agent-composite-answer-planning-curl.md`
- [ ] 7.2 运行原生端全量自动化测试、typecheck 与 lint；AI 默认不启动或操作模拟器/真机。验收：`cd mobile && npm test -- --runInBand && npm run typecheck && npm run lint`
- [ ] 7.3 向用户提供模拟器/真机走查清单，至少覆盖“甲醛是什么 + 来源 + 环保等级”、通用问题、纯知识库、解释 + 统计、partial、fallback 和历史恢复；由用户执行并反馈结果后记录，不由 AI 默认代验。验收：用户反馈与结果摘要写入对应验收记录
- [ ] 7.4 更新 Knowledge Agent 产品形态与迭代记录，只把本 change 实际完成的第一阶段移入已完成；共享执行图和有界覆盖补查继续标明为后续。验收：`openspec validate --all --strict`
- [ ] 7.5 完成后端全量 pytest、Ruff、原生端全量测试/typecheck/lint、`git diff --check` 与 OpenSpec 全量严格校验，按阶段完成本地提交。验收：`cd backend && .venv/bin/pytest -q && .venv/bin/ruff check . && cd ../mobile && npm test -- --runInBand && npm run typecheck && npm run lint && cd .. && git diff --check && openspec validate --all --strict`
- [ ] 7.6 检查遗留问题和后续优化项；先逐条向用户说明背景、原因和影响，只有用户确认后才登记到 `docs/discussions/Grove后续优化清单.md`。验收：`git status --short`
