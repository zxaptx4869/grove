## Context

`add-knowledge-agent-composite-answer-planning` 已将 quick answer 固化为 `CompositeAnswerPlan v1`：原始消息被归并为有序回答义务，模型只提出 retrieval/结构化请求候选，服务端规范化并执行后生成合法 answer、tool fact、Citation 和逐项 coverage。`optimize-knowledge-agent-shared-execution-graph` 又将同一首次计划编译为闭合共享图，能精确去重等价数据集、持久化细粒度节点终态并恢复 pending 节点。

现在 quick 复合路径在首次综合后直接终态提交。coverage 已能证明某个 `grove_only/grove_required` 义务没有合法 Evidence、只得到 limited 结构化事实或有部分工具失败，但服务端没有一个可恢复的“观察覆盖→只针对缺口提出新查询→再综合”边界。本 change 建立一次补查阶段，而不把 quick 扩展成多轮自主工具循环。

关键约束：

- 首次计划、已提交执行输入、共享图节点和 Evidence 是不可重写的恢复事实。
- owner、Workspace、项目、用户和上下文链只能来自 Run；补查模型不能提供范围或对象 id。
- Citation 只能使用当前 Run 已核验 Evidence；结构化数字仍只能来自服务端 tool fact。
- 串行和共享图首次路径都必须受支持，且旧 Run、开关关闭路径和原生端协议不得被破坏。
- 补查失败时“有一份可用的首次回答”比“强行产生新终态”更重要，但 fallback 不得被掩盖。

## Goals / Non-Goals

**Goals:**

- 从首次合法 coverage 确定性筛选可修复 Grove 缺口，每 Run 最多补查一次。
- 让模型只提出新 retrieval/结构化请求候选，由服务端严格规范化目标义务、参数、去重、范围和预算。
- 在任何新工具调用前固化补查控制快照、计划、执行模式和独立总预算。
- 串行与共享图补查都只执行新请求，同时复用同 Run 首次 result/Evidence 并保持可恢复检查点。
- 以首次与补查合并后的合法输入再综合、重算 coverage/basis/Citation/gaps，补查失败则恢复首次合法结果。
- 对取消、Worker 恢复、配置变化、重复消息、Workspace 隔离、可观测和无写入副作用建立硬门禁。

**Non-Goals:**

- 不做第二次补查、多轮自主规划、通用 B2 Agent loop 或多 Agent 协商。
- 不让补查修改首次 requirement、basis policy、statement message 或任何已固化请求。
- 不迁移 investigate、entries 或兼容 quick Workflow，不构建通用 DAG/DSL。
- 不将纯模型漏答或无实际外部工具的 `external_required` 缺口包装为 Grove 工具补查。
- 不接入网络搜索、Operation Plan、`prepare_operation` 或任何知识/候选/事实工作集写入。
- 不新增原生 UI 流程、对外查询图或必填 API 字段。

## Decisions

### 1. 以首次服务端 coverage 而不是工具状态直接决定准入

Runner 先完成现有 `build_composite_answer`，获得经 point/handle/Citation 校验后的首次 `CompositeAnswerResult`。新增纯服务端 `derive_repair_eligibility`，只接受：

- coverage 状态是 `partial` 或 `insufficient`；
- basis policy 是 `grove_only` 或 `grove_required`；
- 缺口原因为缺少 Grove Evidence/tool fact、有限结果或可再查询的输入不完整；
- 当前未取消且尚未进入补查。

`answered`、`failed`、只因最终模型漏输出的 `model_allowed` 义务和没有外部工具的 `external_required` 义务不准入。这样把“工具有命中”与“回答真实未覆盖”分开，也避免用 Grove 内部搜索伪装当前外部核验。

备选方案是只看 execution 中的 empty/limited/error，但它会重查已经由其他依据回答的义务，并漏掉“输入存在但没有形成合法 point”的真实缺口。

### 2. 在调用补查 planner 前固化可恢复基线结果

Run 追加可空内部字段：

```text
coverage_repair_json
coverage_repair_plan_json
coverage_repair_execution_json
coverage_repair_graph_json
coverage_repair_graph_state_json
```

`CoverageRepairSnapshot v1` 保存：阶段、执行模式、冻结预算、可修复 requirement id、首次 `KnowledgeAnswerOut`、coverage、answer basis、Run 状态候选、answer fallback、停止原因与有界错误。基线不写入公开 `answer_json`，避免 processing Run 在轮询中被误投影为终态；它只存在内部控制快照中。

恢复时先解析该快照，不再调用首次综合模型；任何补查失败都能从快照恢复首次合法结果。备选方案是失败时再用首次 execution 重新综合，但这会重复模型调用且可能生成不同回答，不符合恢复语义。

### 3. 补查候选只表达新请求，不复制首次计划

新增 `CoverageRepairPlanDraft v1`，字段限定为：

```text
schema_version
target_requirement_ids
retrieval_requests[]
structured_requests[]
reason
```

它使用已规范化的 `rN` requirement id，不允许输出 requirement 内容、statement message、basis policy、范围、节点、预算或工具名。模型获得原始问题、不可变的义务摘要/依据策略、可修复 id、首次请求摘要、状态/完整性、coverage note 和服务端预算，不获得隐藏思维、原始 prompt、Workspace/项目 id 或未授权对象。

服务端将合法候选规范化为 `CoverageRepairPlan v1`，保留 target 并对新请求使用接续首次请求的稳定 id（例如 `q4/s3`）。计划不包含首次 requirement 或请求副本，因此无法在存储层改写首次 `CompositeAnswerPlan v1`。

### 4. 以独立冻结预算严格限制补查

默认新配置（开关默认关闭）：

| 预算 | 默认值 |
|---|---:|
| 总新查询 | 2 |
| 结构化请求 | 1 |
| 新节点 | 8 |
| 工具调用 | 6 |
| Entry | 20 |
| Evidence | 20 |
| 分组桶 | 16 |
| 补查执行耗时 | 15 秒 |
| 计划 JSON | 12,000 bytes |
| 图 JSON | 16,000 bytes |
| state JSON | 48,000 bytes |
| 控制快照 JSON | 60,000 bytes |

这些值在基线 coverage 准入后写入 `CoverageRepairSnapshot`，恢复始终使用快照值。工具的单次输出仍受既有 B1/复合回答上限限制；补查预算是额外且更小的阶段总上限，不是扩大单工具权限。

默认 2 个查询允许“改写一个语义检索 + 补一个结构化查询”，但不足以演变成调查循环；8 节点刚好容纳两条 retrieval 链或一条 retrieval 与少量聚合输出。更大默认值会让 quick 的时延和资源语义逼近 investigate。

### 5. 在规范化阶段拒绝等价重放，在 Evidence 层复用已有行

新增与执行器无关的 request canonical signature：

- retrieval：工具/协议版本 + 规范化 query + 完整性合同 + 固化 Run 范围；
- structured：B1 规范化 `EntrySetSpec` + outputs/sort/limit + 工具版本 + 固化 Run 范围。

候选中任一 signature 与首次计划或同候选前项重复时，不为它创建新执行工作。若所有请求均重复，固化 `no_novel_request`；若候选混合重复与新请求，拒绝整份候选并记录非法，不静默替模型改计划。这比执行后依赖指纹碰巧命中更易审计。

`create_answer_evidence` 已按同 Run + Entry + Source + Attachment + purpose 复用 Evidence，新查询重新命中已读取来源时沿用句柄，不增加重复 Evidence 行。

### 6. 使用“补查子计划 + 存储适配器”复用串行与共享图执行器

服务端将 `CoverageRepairPlan v1` 转为执行专用 `NormalizedCompositeAnswerPlan`：

- requirements 仍是首次不可变 requirement；
- statement message ids 仍是首次允许集合；
- retrieval/structured 列表只包含补查新请求。

一个轻量 `RepairRunStorageAdapter` 透传 run id/owner/workspace/project/scope，但把现有执行器读写的 `composite_answer_execution_json` 映射到 `coverage_repair_execution_json`，把 `shared_execution_graph_json/state_json` 映射到补查字段。这样：

- 串行首次路径继续使用 `execute_composite_answer_plan`；
- 共享图首次路径继续使用 `execute_shared_execution_graph_plan`；
- 补查有独立 plan digest、图、状态、预算和恢复边界，不覆盖首次快照。

执行模式由基线快照固化：首次已使用共享图就使用补查图，否则使用串行补查。恢复不因当前开关变化换路径。

备选方案是把补查请求追加到首次 plan/graph，但这会破坏首次计划不可变、改变 plan digest，并让旧节点 fingerprint 与冻结预算难以稳定恢复。

### 7. 合并执行快照后再综合，不改写首次输入

新增纯函数 `merge_composite_execution`：

- 先验证首次 input/request id 只来自首次计划，补查 input/request id 只来自补查计划；
- 保留首次 inputs/tool facts 的序列化值与句柄，只在尾部加入补查结果；
- 按稳定 request/kind/handle 排序并拒绝冲突 id/句柄；
- 扩展 `CompositeAnswerExecutionSnapshot.inputs` 内部最大数以容纳首次 5 + 补查 2，但对外仍只投影原 coverage/basis 协议。

合并快照交给现有 `build_composite_answer`，因此 Evidence 句柄关联、服务端 tool fact、数字禁改写、逐义务 coverage 和 answer basis 继续使用同一校验器。补查不创建新 requirement，也不更改自然顺序。

### 8. 再综合失败以基线 answer 保底，服务端事实只在可确定时追加

补查 planner 失败、候选非法、无新请求或所有新工具失败时，直接使用基线 `CompositeAnswerResult` 终态化，但新增补查 purpose 的 fallback/stop 记录仍进入 `run_fallback_summary`。

存在新合法 Evidence/tool fact 时才进行一次再综合。若再综合 fallback：

- 不以 fallback 草稿覆盖基线合法 point/Citation；
- 可以追加不需要模型解释的服务端 tool fact，但必须保留 completeness 措辞；
- 终态不得因“有新工具命中”自动升为 completed，并记录 `coverage_repair_synthesis` fallback。

这一选择保证补查是单调的：成功时可增加合法依据，失败时不会丢掉原回答。

### 9. 持久化阶段是唯一次数与恢复事实源

`CoverageRepairSnapshot.stage` 使用闭合状态：

```text
baseline_ready
→ plan_ready / skipped / failed
→ executing
→ execution_ready
→ completed / failed
```

其中 `skipped/failed/completed` 是补查控制终态，不直接等同于 Run 终态。一旦 `coverage_repair_json` 存在，Worker 就沿用快照内的 execution mode/budget/eligible ids，不再根据当前开关或新 coverage 决定是否进入补查。一旦 plan 字段存在或快照标记 planner 已尝试，恢复不再调用模型。

取消沿用现有 Run cancelled 语义：不把基线内部快照投影成正常回答，不推进工作集；保留已提交内部检查点供审计。

### 10. 内部可观测新增独立 purpose，公开协议不暴露补查图

新增：

- Run step：`coverage_repair_plan`、`coverage_repair_execute`、`coverage_repair_synthesize`；
- model/server purpose：`coverage_repair_plan`、`coverage_repair_graph`、`coverage_repair_synthesis`；
- stop reason：`not_needed`、`not_repairable`、`no_novel_request`、`budget_exhausted`、`planner_failed`、`execution_failed`、`synthesis_failed`、`completed_with_gaps`、`completed`。

实际模型调用记录 provider/model/fallback/error/duration/usage；实际工具记录 status/completeness/duration/复用信息；确定性跳过不伪造模型或工具调用。现有 Run 与消息页仍只返回 answer/points/Citation/coverage/gaps/basis/fallback 和既有计划摘要，不返回补查 query、graph、node、fingerprint、范围或内部错误堆栈。

### 11. 无写入边界用工具注册表、范围重建和评估计数三层保护

补查只使用现有 `semantic_search/read_entries/read_source_evidence/query_entries/aggregate_entries` 只读适配器，不向 planner 暴露 registry 中的任意工具名。每次执行都从父 Run 构建 `RunToolContext`，共享图并行任务仍使用独立 `AsyncSession`。

评估在补查前后统计 Entry、Source、Candidate、Draft/Extraction、目录、Operation 与事实工作集，只允许 Conversation/Message/Run/当前 Run Evidence/审计/回答快照变化。工具 schema 、服务范围校验和数据库评估共同防止仅靠 prompt 维持边界。

## Risks / Trade-offs

- **[首次综合增加一次模型成本后补查可能再增加两次]** → 只有可修复 coverage 才规划，只有新合法结果才再综合；查询和 15 秒补查预算严格限定 quick 尾延迟。
- **[coverage note 分类错误导致无效补查]** → 准入不解析自由文本 note 作为唯一依据，而是联合 basis policy、合法句柄、input status/completeness 和依据缺失派生可修复 reason enum。
- **[候选与首次查询只是文字不同但语义重复]** → 一期只拒绝可证明的精确规范化等价，不用向量或模型模糊去重；偶发重复优化不影响安全，错误合并则会污染回答。
- **[内部快照包含基线 answer 可能接近 TEXT 上限]** → 独立 60KB 字节门禁、Pydantic 闭合 schema 和字段级长度限制；无法完整保存基线时不进入补查，不截断合法回答后继续。
- **[存储适配器隐藏 ORM 字段错误]** → 适配器仅映射五个明确执行字段，其余范围字段只读透传；增加串行/图检查点往返、配置变化和损坏快照测试。
- **[补查部分结果可能让最终文字变差]** → 完整保留基线结果；再综合 fallback 或合法覆盖退化时使用基线，只有新 coverage 不低于基线且没有丢失已回答义务时才接受新 answer。
- **[补查开关关闭导致进行中 Run 漂移]** → 快照存在后只读快照的 execution mode/budget/attempted 状态，新配置只影响还没有基线快照的新 Run。
- **[默认关闭延迟产品收益]** → 先通过串行/共享图评估与原生兼容走查，再由部署配置逐步开启；开关不改变已固化 Run。

## Migration Plan

1. 为 `knowledge_agent_runs` 追加五个可空 TEXT 字段，旧行保持 `NULL`；完成 SQLite/MySQL 8 迁移往返与旧 Run 投影测试。
2. 增加默认关闭的补查开关、闭合候选/快照类型、准入与规范化纯函数；先不接入 Runner。
3. 实现存储适配器、串行/共享图补查执行、检查点恢复和 execution 合并，完成无重放测试。
4. 接入 Runner 的基线固化、补查规划、执行、再综合和失败保底，保持原生端和公开 API 无新必填字段。
5. 在开关关闭、串行、共享图、取消、恢复、配置变化、损坏快照和补查失败下完成自动化、curl 和原生协议兼容验证。
6. 本地验证完成后保持 change 活动；用户真机走查通过并明确确认后才归档，归档/推送/合并不在当前授权中。

回滚时新部署关闭补查开关；未开始补查的新 Run 继续旧路径，已有 `coverage_repair_json` 的进行中 Run 仍按冻结快照恢复。数据库 downgrade 只能在没有需要恢复的补查 Run 后执行，否则会丢失内部审计/恢复快照。

## Open Questions

无阻塞实施的产品歧义。默认预算、可修复准入和“再综合不得覆盖更好基线”已在本 design 固定；实际评估若显示某个上限在不改变阶段语义下需收紧，可在当前 change 内更新工件和测试；若需扩大轮次、接入外部工具或迁移 Workflow，则属于后续 B2/外部工具 change。
