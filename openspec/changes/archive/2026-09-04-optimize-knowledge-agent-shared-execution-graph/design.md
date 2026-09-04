## Context

`add-knowledge-agent-composite-answer-planning` 已为 `actual_result_mode=answer && actual_answer_mode=quick` 建立 `CompositeAnswerPlan v1`：模型只提出有界回答义务和检索/结构化请求，服务端规范化后按 retrieval → structured 的固定顺序逐份执行，再生成工具事实、逐项覆盖和最终回答。阶段 B1 已提供受限 `EntrySetSpec`、`query_entries`、`aggregate_entries`、完整性语义和只读 dispatcher。

当前执行器以“原始请求”为复用边界。两份请求即使使用同一语义条件或同一结构化集合，仍可能分别召回、读取或聚合；同一集合上的 count、group 和 entries 只在单份 B1 请求内部共享，不能跨复合请求复用。恢复检查点也以原始请求为单位，无法让后续覆盖补查稳定引用更细粒度的已完成结果。

本 change 只优化第一阶段 quick 复合回答的服务端执行层。原始 `CompositeAnswerPlan v1`、回答义务、最终 answer/points/Citation/coverage/basis 和原生端交互继续作为外部契约；共享图完全由应用从已规范化计划编译，模型与客户端都不能直接提交图、依赖、范围或调度参数。

关键约束：

- owner、Workspace、项目、上下文链和工具范围只来自 Run 固化状态；节点复用不得跨 Run。
- 精确统计、limited/unknown、Evidence 核验和逐义务依据规则继续以现有主规格为准，优化不能放宽语义。
- `AsyncSession` 不能被并发任务共享；并行节点必须使用隔离会话，且共享 Run、Evidence、审计和检查点写入由协调器串行提交。
- 已执行图不能在错误后整体改走旧串行路径，否则会重复调用并产生语义漂移。
- 当前 change 不观察覆盖结果生成新计划；它只执行首次固化计划。

## Goals / Non-Goals

**Goals:**

- 把规范化复合请求确定性编译为版本化、闭合且有界的共享只读执行图。
- 对完全等价的数据集和输出节点去重，一个结果可以通过消费者映射服务多个回答义务。
- 校验节点类型、依赖、无环性、消费者和总预算，并以确定性拓扑顺序执行。
- 对明确安全的独立只读节点实施小并发，保持全局对象、Evidence、工具调用和耗时预算确定。
- 逐节点提交有界结果；恢复只重放未提交节点，最终投影回现有复合执行快照。
- 记录节点实际状态、完整性、耗时、复用、错误和图级 fallback，禁止优化掩盖降级。
- 为下一 change 的覆盖缺口补查提供稳定 node/result handle 和已完成结果复用基础。

**Non-Goals:**

- 不修改 planner 让模型输出 DAG，也不允许模型指定 node id、fingerprint、depends_on 或并行度。
- 不根据覆盖结果补查、重规划或形成多轮工具循环。
- 不迁移 investigate、独立 entries 或旧 quick 执行图；不建设所有 Agent 共用的通用工作流引擎。
- 不做模糊查询合并、语义近似去重或跨 Run 缓存，只合并服务端能证明完全等价的节点。
- 不改变回答/API/原生 UI，不暴露内部查询图或执行时序。
- 不接入外部搜索、知识写入、`prepare_operation`、多 Agent 或后台无限任务。

## Decisions

### 1. 图由服务端从 `CompositeAnswerPlan v1` 编译，不新增第二次规划

新增 `SharedExecutionGraph v1` 作为内部执行快照。编译器读取已持久化的规范化复合计划和 Run 固化预算，生成服务端节点、依赖与消费者映射；不调用模型，也不接受客户端图字段。图至少包含：

```text
SharedExecutionGraph v1
├── plan_digest
├── frozen_budget
├── nodes[]
│   ├── id                    n1..nN，服务端稳定编号
│   ├── kind                  闭合节点类型
│   ├── fingerprint           服务端生成
│   ├── dependencies[]        服务端推导
│   ├── consumer_request_ids[]
│   ├── consumer_requirement_ids[]
│   ├── normalized_params     内部持久化，不向客户端投影
│   └── parallel_eligible
└── original_request_map      用于投影回 v1 执行快照
```

选择服务端编译而不是让 planner 直接输出 DAG，是因为第一阶段计划已经表达用户语义，图只是等价执行优化。让模型控制依赖会扩大 schema、失败面与权限边界，也会把“结果正确”错误地依赖于模型调度能力。

### 2. 使用少量领域节点，而不是通用任务语言

第一版节点类型限定为：

- `semantic_entry_set`：执行有界语义召回并产生有序 Entry 句柄与 limited/unknown 完整性；
- `structured_entry_set`：保存已校验的逻辑 `EntrySetSpec`，供确定性输出节点引用；
- `entry_list`：对上游集合产生有界稳定 Entry 快照；
- `entry_content`：读取上游选定 Entry 的当前内容和来源引用；
- `entry_evidence`：核验上游内容节点的 Source/Attachment 并产生当前 Run Evidence；
- `aggregate_count`：对上游集合产生 count；
- `aggregate_group_count`：对上游集合按一个白名单维度分组。

retrieval request 编译为 `semantic_entry_set → entry_content → entry_evidence`；structured request 编译为一个 entry-set 节点及其 count/group/list 输出节点。多个输出只引用同一集合，不复制集合。第一版不提供条件分支、任意函数、脚本、写节点或模型节点。

使用领域节点而不是通用 DAG DSL，可以复用 B1 校验与 dispatcher，并让依赖、预算和完整性规则保持可证明。未来确有新只读工具时再增加闭合节点类型和版本。

### 3. 只做规范化参数的精确等价合并

节点 canonical key 至少包含：节点 schema/tool 版本、节点 kind、规范化数据集或查询参数、排序/输出参数、固化预算合同、上游 canonical key 和 Run 范围指纹；不包含 requirement id、原始 request id 或模型生成 id。相同 key 合并为一个节点，消费者集合取并集。

语义文本只做现有 `_clean_text` 级空白规范化，不做向量相似、同义改写或大小写之外的猜测性合并。不同过滤条件、不同完整性合同、不同排序、不同预算或不同上游均不得合并。`semantic_entry_set` 与含相同 semantic query 的结构化集合只有在过滤、候选预算和结果合同全部一致时才能共用，否则保留独立节点。

选择精确等价而不是“相似查询自动合并”，是为了保证优化前后语义等价；漏掉一次可合并机会只影响性能，错误合并会直接污染回答与 Citation。

### 4. 依赖和预算由编译器派生并做完整图校验

编译完成后，服务端必须检查：

- node id、fingerprint 唯一，kind 与参数 schema 闭合；
- 依赖存在、方向合法、无自依赖、无环，且深度、入度、节点数受限；
- 每个非根节点有合法上游，每个执行节点至少有原始请求或回答义务消费者；
- requirement/request 映射只引用原规范化计划中的对象；
- 图的逻辑请求、实际工具调用、Entry、Evidence、分组桶、JSON 字节、总耗时和并发度不超过服务端预算；
- 模型或客户端字段不能进入范围指纹、依赖、预算或执行参数。

建议初始默认值为最多 24 个节点、深度 4、单节点最多 4 个直接依赖、并发度 2；实际可执行工具调用仍不得超过由原计划上限推导出的固定总预算。数值以配置形式存在，实施时可在不扩大产品范围的前提下通过测试夹具校准。

### 5. 先固化完整图和预算，再执行任何节点

Run 追加可空 `shared_execution_graph_json` 和 `shared_execution_state_json`：

- graph 保存首次编译结果、计划摘要指纹和冻结预算；
- state 保存按 node id 稳定排序的节点终态、完整性、有界结果句柄、错误与实际耗时；
- 两列均使用闭合 Pydantic schema 和独立 TEXT 字节上限；旧 Run 保持 `NULL`，不回填、不猜测。

首次成功编译后在任何图节点调用前提交 graph。恢复时只接受与当前固化 plan digest 一致的快照，并始终使用图内冻结预算；部署后配置变化不能重写进行中的图。非法、超限或摘要不匹配的已持久化快照必须显式失败，不能重新编译或改走串行路径。

选择新增快照而不是把现有 `CompositeAnswerExecution v1` 原地改成 v2，是为了让开关回退、旧 Run 和现有综合器继续工作，并降低迁移风险。

### 6. 图完成后确定性物化现有复合执行快照

协调器把节点 state 按 `original_request_map` 聚合为现有 `CompositeAnswerExecutionSnapshot`：

- 每份原始 request 仍得到一个 input 状态、完整性、Entry/Evidence/result handles 和错误摘要；
- tool fact 由对应输出节点的服务端结果生成，requirement 关联取消费者映射而不是数据节点身份；
- 多个原始请求复用同一节点时共享稳定结果句柄，但各自的义务覆盖仍独立校验；
- 原有综合、Citation 校验、coverage、answer basis 和公开投影继续消费物化后的兼容快照。

这样执行优化不要求同时重写回答协议，也为 A/B 比较串行与共享图结果提供同一输出边界。

### 7. 调度采用确定性拓扑波次，只有白名单节点可并行

调度器使用 Kahn 拓扑算法形成 ready 集合，以稳定 node id 作为准入和持久化排序。每个波次先按稳定顺序为节点冻结本次对象、Evidence、桶和工具调用额度，再启动最多配置并发度的节点；同波次未使用额度不转让给已启动的兄弟节点，只能由后续波次按确定性规则重新分配。

第一版并行白名单只包含没有共享可变上下文、不会直接写 Run/Evidence/审计且能使用独立数据库会话返回有界 `NodeOutcome` 的只读节点。`entry_evidence`、检查点写入、工具审计和最终物化由协调器串行执行；不满足条件的节点即使拓扑独立也串行。SQLite 与 MySQL 8 使用同一语义，不依赖数据库特定锁行为获得正确性。

并行任务不得共享 `AsyncSession` 或可变 `RunToolContext`。每个任务使用从 Run 固化范围构造的不可变上下文和独立会话，只返回候选结果；协调器重新校验 node/fingerprint、取消和预算后，按 node id 更新 state 并提交。迟到或已取消结果直接丢弃。

选择“小并发白名单”而不是对所有 ready 节点 `gather`，是因为 Evidence、工具序号和全局预算包含共享写状态；安全性和确定性优先于最大吞吐。

### 8. 恢复复用节点终态，不复用 `running` 内存状态

节点持久状态使用 `completed / empty / limited / partial / failed / cancelled`，未提交节点视为 pending；不把进程内 running 当作可恢复事实。每个可复用终态必须同时匹配 graph version、node fingerprint、上游结果指纹和冻结预算。`limited`、`partial` 与 `failed` 都表示本次节点尝试已完成，恢复不得因“也许可以更好”而自动重试；后续覆盖修复如需补查，必须创建受预算约束的新节点而不是改写旧结果。

节点执行异常只影响该节点和依赖它的后继：已有独立合法结果继续保留，受阻后继标记 failed/partial 并进入现有缺口语义。图已经开始执行后不得整体回退串行执行器。

### 9. fallback 分为编译前兼容回退和执行后诚实部分结果

独立开关 `KNOWLEDGE_AGENT_SHARED_EXECUTION_GRAPH_ENABLED` 默认关闭。关闭时完全沿用当前串行执行器。

开关开启后：

- 图尚未持久化且编译、校验或首次持久化失败：记录 `shared_execution_graph` 的 server fallback，然后调用当前串行执行器；
- 图已持久化但尚无节点终态时发生可证明无副作用的调度初始化错误：允许记录 fallback 并串行执行；
- 任一节点结果已提交后发生节点或调度错误：不得全量串行重跑，只保留合法节点并形成 partial/failed；
- 已持久化图/state 非法或摘要不一致：Run 显式失败，禁止猜测恢复。

这一区分避免性能优化故障直接破坏可用性，同时防止执行一半后重复调用被伪装为正常回退。

### 10. 节点级可观测性由协调器串行落库

每个实际工具调用继续记录真实 tool name、status、error、duration 和最小化参数/结果摘要，并追加 graph/node fingerprint、复用状态和消费者数量等内部审计信息。被合并的逻辑消费者不伪造多次工具调用；API 如需显示次数，以实际调用为准。

并行执行器返回模型调用 meta 和工具 outcome，由协调器顺序写入现有 invocation/tool-call 表，避免并发计算 `sequence`。节点复用本身记录 `reused=true`，但不创建第二条“成功调用”。图编译失败、节点失败、并行降级为串行和预算限制都必须进入 fallback/状态摘要，接口成功不能掩盖真实降级。

### 11. 本 change 不改变事实工作集和任何正式对象

图只读取当前 Run 合法正式 Entry 和 Source/Attachment，并写入 Run、当前 Run Evidence、模型/工具审计和回答快照。搜索命中、数据集成员、统计结果和未被最终引用的 Entry 都不得推进事实工作集；不得创建或修改 Entry、Source、Candidate、Draft、目录或 Operation。

## Risks / Trade-offs

- **[图编译后节点数量反而增加]** → 同时限制逻辑请求、图节点和实际工具调用；只有能证明复用或依赖价值的拆分才进入图。
- **[错误等价合并污染多个义务]** → canonical key 包含版本、规范化参数、上游、范围和预算；第一版只做精确等价，不做语义近似合并。
- **[并行导致预算或结果不确定]** → 波次开始前稳定分配额度，使用独立会话，协调器按稳定 node id 校验和持久化。
- **[SQLite 写锁或 AsyncSession 并发错误]** → 并行节点只返回只读 outcome，共享写入和 Evidence 节点串行；测试同时覆盖 SQLite，MySQL 8 行为用方言/集成测试校验。
- **[新旧双份执行快照不一致]** → graph state 是执行事实源，兼容 execution v1 只由一个确定性物化器生成并进行往返/恢复测试。
- **[编译失败回退掩盖问题]** → 独立 server fallback 可观测；只有没有已提交节点结果时允许串行回退。
- **[图 state 超过 TEXT 上限]** → 只保存受控句柄、摘要和错误，分别设置字节预算；不能压缩时显式失败，不静默截断关键状态。
- **[性能优化没有真实收益]** → 评估以实际底层调用次数、重复集合消除数和端到端阶段耗时为主，不用不稳定的单元测试墙钟时间作为唯一门槛。
- **[为下一 change 过度设计]** → 只预留稳定 node/result handle 和终态复用，不实现补查计划、动态扩图或覆盖循环。

## Migration Plan

1. 追加两个可空 Run JSON 字段和图预算配置，默认关闭；先完成 SQLite/MySQL 8 迁移往返和旧 Run 兼容测试。
2. 实现纯函数图编译、canonical fingerprint、校验、状态恢复和兼容快照物化，不接入 runner。
3. 实现串行图调度与节点检查点，验证其输出与当前串行执行器等价。
4. 加入白名单小并发和独立会话，完成预算、取消、失败、恢复与可观测测试。
5. 在 runner 中以独立开关接入；开发环境先对代表性复合问题启用并比较实际调用次数、结果完整性和回答协议。
6. 用户完成原生端兼容走查后再归档。生产回滚优先关闭共享图开关；已有图 Run 继续按固化图恢复，不能切换为串行重跑。确认没有进行中图 Run 后，才可按变更窗口回退数据库迁移。

## Open Questions

- 初始节点数、深度和并发上限暂定 24 / 4 / 2，实施时用现有复合评估集校准；调整不能超过原计划逻辑请求和工具总预算。
- 第一版是否允许 `semantic_entry_set` 跨 retrieval 与 structured request 复用，取决于两条现有路径能否统一成完全相同的候选与完整性合同；若无法证明等价，本 change 宁可只在同类请求内去重。
- 原生端没有新 UI，手动走查以“同一问题回答内容、Citation、partial/fallback 与历史恢复不回退”为准；性能收益主要通过服务端审计与评估夹具验证。
