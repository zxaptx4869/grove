## 1. 数据、协议与兼容骨架

- [x] 1.1 增加 `StructuredQueryPlan v1`、`EntrySetSpec v1`、结构化输出、工具状态与完整性领域类型，并配置结构化查询特性开关、计划/输出/调用/桶数/耗时/字节预算；所有模型可控字段使用闭合枚举和长度限制。验收：`cd backend && .venv/bin/ruff check app/agents app/core/config.py app/models/knowledge_agent.py app/schemas/knowledge_agent.py`
- [x] 1.2 以追加 Alembic 迁移为 Knowledge Agent Run 增加可空规范化查询计划快照字段，不回填或猜测旧 Run；迁移必须兼容 SQLite 与 MySQL 8，并明确降级/回滚只移除新增列。验收：`cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic current`
- [x] 1.3 将 `entry_result_json` 协议扩展为向后兼容的 v2，保留 v1 的 query、items、分页、完整性与助手兼容字段，新增集合摘要、排序、聚合块和分输出完整性；API 能同时读取旧 v1 和新 v2。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_api.py tests/test_knowledge_agent_conversations.py tests/test_knowledge_agent_structured_entry_search.py`

## 2. 一次结构化计划与服务端校验

- [x] 2.1 实现版本化 structured query planner 提示与结构化输出，只在 `actual_result_mode=entries` 且新开关开启时调用；记录 purpose、provider、model、fallback、error、duration、prompt version 和 usage。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_models.py -k structured_query`
- [x] 2.2 实现 `EntrySetSpec` 规范化与硬校验：范围只从 Run 注入；允许 semantic_query、main_type、info_nature、UTC 更新时间区间和受限排序；拒绝项目/目录/Entry id、未知字段、任意运算符、SQL、无语义相关性排序及相互矛盾时间范围。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_structured_query.py -k validation`
- [x] 2.3 校验共享集合上的 entries/count/group_count 输出、去重、稳定执行顺序和服务端预算；计划非法、模型未配置或调用失败时显式回退旧结构化查找，不生成聚合或精确承诺。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_structured_query.py -k 'plan or fallback or budget'`
- [x] 2.4 持久化服务端规范化后的计划快照而非原始模型输出；同 `client_message_id` 重试和已有计划的恢复不得再次规划或改变计划。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_worker.py -k structured_query_plan`

## 3. 受控只读执行器与确定性工具

- [x] 3.1 建立应用控制的只读工具 registry/dispatcher，统一注入 Run 可信上下文、工具版本、预算、取消检查、状态与有界审计；未知工具不得通过动态导入、反射或名称猜测执行。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_read_tools.py -k dispatcher`
- [x] 3.2 实现 `query_entries` 的纯结构化范围查询，只读取正式 Entry，支持 main_type、info_nature、UTC updated_at 过滤及 updated_at/created_at 稳定排序，并以 Entry id 作为 tie-breaker。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_structured_query.py -k query_entries`
- [ ] 3.3 将可选 semantic_query 接入既有混合召回与重排，再与结构化条件组合；相关性集合必须标记 limited/unknown，不能因局部关键词命中或 top-k 返回而声明完整。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_structured_query.py -k semantic`
- [ ] 3.4 实现 `aggregate_entries` 的直接 count 与按 main_type、info_nature、UTC updated_month 分组，不能从截断 Entry 列表反推；空 info_nature 统一为 unspecified，SQLite/MySQL 8 的时间桶、空值和稳定顺序语义一致。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_structured_query.py -k aggregate`
- [ ] 3.5 实现共享集合上的“统计 + 分组 + 列表”执行和分输出完整性派生；分别处理列表 limit、聚合桶、语义候选、超时、对象失效与 JSON 字节截断。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_structured_query.py -k 'combined or completeness or truncation'`
- [ ] 3.6 将 query/aggregate 及既有搜索/Entry/Evidence 读取适配为统一调用状态和最小化审计，保持已发现集合、原文核验与 Citation 权限不变；审计不得复制完整 Entry、Source 原文或 prompt。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_read_tools.py tests/test_knowledge_agent_evidence.py`

## 4. Run 编排、恢复与终态一致性

- [ ] 4.1 将一次结构化计划与确定性工具执行接入现有 entries Runner：旧开关关闭时沿用既有固定查找，开启时按“计划 → 固化 → 工具 → v2 快照 → 终态”执行，不改变 answer、quick 或 investigate 分支。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_structured_entry_search.py -k entries`
- [ ] 4.2 为每个工具调用生成同 Run、工具版本和规范化参数绑定的稳定指纹；恢复时复用已提交调用结果、只重放未完成只读步骤，并在对象状态变化时返回真实快照/异常边界。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_worker.py -k 'structured_query or tool_call'`
- [ ] 4.3 在规划前后、每个工具前后和终态前检查取消，确保迟到计划/工具结果不提交；v2 快照、助手兼容消息、Run 终态和活动槽必须原子提交，部分失败不得留下相互矛盾的聚合与列表。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_worker.py tests/test_knowledge_agent_result_protocol.py -k 'cancel or structured_query'`
- [ ] 4.4 扩展 Run、消息页、结果分页与可观测 API，返回规范化计划摘要、v1/v2 结果、分输出完整性和真实 fallback；历史分页只读取同一快照，不重新规划或查询。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_api.py tests/test_knowledge_agent_conversations.py tests/test_knowledge_agent_structured_entry_search.py`

## 5. 原生端结构化统计与历史恢复

- [ ] 5.1 扩展原生领域类型、snake_case 适配和 API 客户端以解析 v2 集合摘要、count/group_count、排序和分输出完整性，同时保持 v1 与缺字段服务端兼容。验收：`cd mobile && npm test -- --runInBand src/knowledge-agent/api.test.ts src/knowledge-agent/adapters/entryResults.test.ts`
- [ ] 5.2 在现有 entries 结果内实现“范围/筛选 → 完整性 → 统计/分组 → 排序 → Entry 卡”展示；只有 complete count 使用“共 N 条”，limited/unknown 使用本次匹配边界，客户端不从卡片数量自行计算聚合。验收：`cd mobile && npm test -- --runInBand src/knowledge-agent/components/components.test.tsx -t '结构化查询|精确计数|分组'`
- [ ] 5.3 覆盖空集合、未标注 info_nature、长分组、桶截断、聚合成功但列表 partial、分页失败与旧 v1 结果；打开历史 Entry 继续读取当前对象并显示已更新/不可用。验收：`cd mobile && npm test -- --runInBand src/knowledge-agent/components/components.test.tsx src/knowledge-agent/hooks/useConversationController.test.tsx -t '查询结果|历史|分页'`
- [ ] 5.4 保持现有自动/综合回答/知识列表覆盖和纠正动作；结构化统计不新增顶层结果形态，不显示 Citation、写入动作、勾选或批量操作，并满足三目标视口与辅助名称要求。验收：`cd mobile && npm test -- --runInBand src/knowledge-agent/state/modes.test.ts src/knowledge-agent/components/components.test.tsx -t '结果形态|可访问|结构化查询'`

## 6. 代表性评估与自动验证

- [ ] 6.1 建立结构化查询评估夹具，覆盖精确筛选/计数/排序/分组、统计后列对象、语义与结构化组合、自然语言日期和结果形态路由，不按单条问法增加关键词规则。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_structured_query_eval.py`
- [ ] 6.2 增加安全硬门禁：跨 Workspace/项目结果为零、Candidate/Draft/Extraction 不进入集合、任意 SQL/对象 id/未知工具被拒绝、查询不写知识或推进工作集、语义 top-k 不产生精确总数。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_structured_query_eval.py -k guardrail`
- [ ] 6.3 增加 SQLite 与 MySQL 8 方言查询生成/集成覆盖，验证时间闭开区间、UTC 月桶、NULL 归一化、稳定排序、精确计数和索引使用；根据 Explain/基准决定是否增加组合索引并记录理由。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_structured_query.py tests/test_migrations.py -k 'dialect or aggregate or migration'`
- [ ] 6.4 完成迁移往返、后端全量测试与静态检查。验收：`cd backend && .venv/bin/alembic upgrade head && .venv/bin/pytest -q && .venv/bin/ruff check app tests alembic`
- [ ] 6.5 完成原生端全量单测、类型检查与 lint。验收：`cd mobile && npm test -- --runInBand && npm run typecheck && npm run lint`
- [ ] 6.6 运行 `openspec validate --all --strict`，确认新增能力和四组主规格增量均严格通过，且没有覆盖现有已上线行为。

## 7. 手动走查与收尾

- [ ] 7.1 启动后端后用 curl 验证 Conversation、消息提交、Run 查询、v1/v2 结果分页与可观测接口返回预期 401/200 而非 404，并记录精确统计、语义有限统计、组合结果、非法计划、fallback、取消与恢复响应。验收：将命令和响应摘要写入 `docs/验收记录/add-knowledge-agent-structured-query-tools-curl.md`
- [ ] 7.2 在 360×800、390×844、412×915 走查纯列表、精确统计 + 列表、limited 语义统计、长分组、空结果、partial、历史恢复、分页与 Entry 当前状态变化；记录截图、控制台结果和剩余差异。验收：在对应验收记录中列出三视口结果与截图路径
- [ ] 7.3 更新 Knowledge Agent 产品形态与迭代记录，只把本 change 实际完成的 B1 能力移入已完成；B2 的多轮工具规划和固定 Workflow 迁移继续明确为后续，不提前覆盖主规格。验收：`openspec validate --all --strict`
- [ ] 7.4 检查本 change 的遗留问题与后续优化项；逐条向用户说明背景、原因和影响，用户同意后再登记到 `docs/discussions/Grove后续优化清单.md`。验收：`git status --short`
