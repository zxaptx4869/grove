## Why

Knowledge Agent 当前在真正读取知识前，先把整条普通问题压缩成单一回答依据策略；当用户同时要求概念解释、个人知识、结构化统计或比较时，这种二选一式路由既无法知道知识库实际覆盖，也容易在 `standalone_query` 改写或最终综合中遗漏部分原始请求。阶段 B1 已提供安全的结构化只读工具，现在需要先为普通综合回答建立“多回答义务 + 一次受控执行 + 逐项覆盖”的纵向闭环，再谈执行图优化和补查循环。

## What Changes

- 为 `actual_result_mode=answer` 的 auto/quick 路径增加版本化复合回答计划：从原始消息归并出有界回答义务，为每项记录预期回答、依据要求和可满足它的受控输入；不再要求整条消息只有一个意图或一种依据。
- 原始消息、`standalone_query`、Run 固化范围和上下文链分别保存并传递；检索改写只能辅助查询，不得替代原始请求或丢失“结合/仅使用我的知识库”等限制。
- 服务端严格校验模型候选计划，拒绝范围字段、对象标识、未知能力、循环依赖、超预算计划和对用户限制的放宽；显式 `knowledge_only` 继续对全部回答义务生效。
- 在一次受控执行中复用现有 quick Grove 检索/Evidence 链路和阶段 B1 的结构化查询工具，并允许最终综合使用经计划许可的当前用户陈述与模型通用知识；混合统计问题仍返回 `answer`，精确性继续由工具输出完整性决定。
- 最终回答使用绑定回答义务的结构化要点与覆盖状态；服务端校验每项均为已回答、部分回答、缺少依据或执行失败，并从合法 Evidence 与工具结果派生实际依据和整体状态，避免零散 Citation 掩盖漏答。
- 为计划、执行输入、逐项覆盖、fallback、provider/model/usage 和历史恢复增加可观测及兼容字段；旧客户端、旧 Run、既有 `answer`/`points`/`citations` 和 `entries` v1/v2 协议继续可读。

### Non-Goals

- 不实现共享数据集 DAG、跨义务查询去重、拓扑调度或并行优化；这些属于 `optimize-knowledge-agent-shared-execution-graph`。
- 不实现基于覆盖缺口的第二轮工具规划、自主补查或多轮循环；这些属于 `add-knowledge-agent-bounded-coverage-repair`。
- 不全面迁移或移除既有 quick/investigate 固定 Workflow，不改变显式深度调查语义，也不改变独立 `entries` 结果分支。
- 不接入联网搜索，不把模型训练知识描述为实时外部材料。
- 不进入 `prepare_operation`，不创建或修改 Entry、Source、Candidate、Draft、目录或事实工作集。
- 不新增必须由客户端理解的顶层结果类型，也不在本 change 重做原生对话界面。

## Capabilities

### New Capabilities

- `knowledge-agent-composite-answer-planning`: 定义复合回答义务、一次候选执行计划、服务端校验、逐项覆盖与最终综合的端到端行为。

### Modified Capabilities

- `knowledge-agent-answer-basis`: 将普通综合回答的单一依据选择扩展为逐回答义务的依据要求，同时保持用户全局限制和实际依据可追溯。
- `knowledge-agent-run`: 固化复合回答计划、受控执行与覆盖快照，并保持取消、恢复、终态原子性和 AI/工具可观测。
- `knowledge-agent-structured-entry-search`: 自动结果形态路由需把同时包含解释、知识和统计的请求保留为综合回答，而不是强制压缩成纯 Entry 结果。
- `knowledge-agent-structured-query-tools`: 允许经校验的普通回答计划只读调用既有结构化集合与聚合工具，并继续遵守完整性、范围和预算语义。
- `structured-answer-points`: 结构化要点增加回答义务绑定和逐项覆盖校验，同时保留旧 points 与纯文本 answer 兼容。
- `knowledge-agent-conversation`: 历史消息和 Run 恢复返回生成时的复合计划摘要与覆盖结果，旧客户端缺字段时继续按旧协议工作。

## Impact

- 后端将涉及 Knowledge Agent 规划模型、Run/消息 schema 与可空持久化字段、普通 answer Runner、只读工具适配、Evidence/回答校验、可观测汇总及 Alembic 迁移。
- API 只追加可选字段并保留现有 `actual_result_mode=answer`、`answer`、`points`、`citations`、basis 和 entries 协议；原生端只需验证未知字段兼容及现有回答状态展示，不新增交互入口。
- 测试需要覆盖多意图归并、显式依据限制、原始消息保真、一般解释 + Grove 知识、解释 + 精确统计、部分覆盖、非法计划、模型/工具降级、取消恢复、Workspace/项目隔离和查询零写入。
