## Context

当前 Knowledge Agent 普通问题依次经过上下文决策、结果形态路由、单一依据规划、回答模式路由，再进入 model-only quick、Grove quick 或 investigate。`BasisRouteDraft` 只能为整条消息选择 `knowledge_only`、`knowledge_first`、`model_first`、`hybrid` 或 `external_needed`；后续执行主要使用 `standalone_query`。这套结构适合单一目标，但会把“先解释甲醛是什么，再结合我的知识说明来源和环保等级”压缩成一种依据策略，也无法表达“解释 + 精确统计”同时成立。最终回答模型虽然负责综合，却没有服务端可校验的逐项回答义务，因此可能只回答已召回的部分而静默遗漏其他部分。

阶段 B1 已建立 `EntrySetSpec`、`StructuredQueryPlan v1`、受控只读 dispatcher、`query_entries`、`aggregate_entries`、分输出完整性和 v2 Entry 结果快照。它只接入 `actual_result_mode=entries`，没有改变 quick/investigate。当前 change 在此基础上为普通 auto/quick 综合回答增加一个可恢复的纵向闭环；不把远期的通用 DAG 调度器或覆盖补查循环提前塞入。

关键约束：

- 用户、Workspace、项目和上下文链只能来自 Run 固化状态；模型计划不能包含授权范围。
- 用户原始消息是回答义务和依据限制的权威输入；`standalone_query` 只是检索辅助表达。
- 只有服务端确认完整执行的纯结构化集合才能形成精确统计；语义 top-k、预算截断和部分失败继续 limited/unknown。
- Grove Citation 只能来自当前 Run 重新读取并核验的 Evidence；模型知识、用户陈述和结构化工具事实不能伪装成 Citation。
- 所有 AI/工具阶段必须保留 provider、model、fallback、error、duration、usage 和真实状态。
- 旧客户端、旧 Run、现有 answer/points/citations、entries v1/v2 和显式 investigate 必须兼容。

## Goals / Non-Goals

**Goals:**

- 用一个版本化、闭合且有界的复合回答计划表达一条消息中的多个回答义务，而不是为整条消息选择唯一意图或唯一依据。
- 让一个受控输入请求能够服务一个或多个回答义务，并在固定阶段内使用现有 Grove 检索/Evidence 与 B1 结构化工具。
- 让最终综合按回答义务输出结构化要点，服务端能够识别漏答、缺少依据、工具失败和外部材料缺口。
- 对结构化统计使用服务端生成的不可改写事实要点，避免模型把 limited 结果包装成精确全集或改写数值。
- 固化计划与执行检查点，使同一 Run 重试、Worker 恢复和历史读取不重新规划或漂移。
- 通过特性开关渐进上线，并让失败显式回退现有 quick 路径而非静默改变回答依据。

**Non-Goals:**

- 不建设通用共享数据集 DAG、跨请求公共子表达式消除、拓扑调度或并行执行器。
- 不根据覆盖结果发起第二轮检索、第二份计划或自主工具循环；回答输出结构校验的一次有界模型重试不属于工具补查。
- 不迁移显式或自动选择的 investigate 执行图，不移除既有 basis/quick/investigate 兼容逻辑。
- 不改变显式 `entries` 的 B1 执行与 v1/v2 结果协议，不新增第三种顶层结果形态。
- 不接入外部搜索，不进入 `prepare_operation`，不提供任何知识或目录写入能力。
- 不重做原生端视觉与交互；新可选字段可以被旧客户端忽略。

## Decisions

### 1. 顶层结果形态只决定展示，复合问题进入 answer

自动结果形态路由仍输出 `answer` 或 `entries`，但语义收窄为最终展示：纯对象查找、纯筛选/统计且用户主要需要结果集时可以进入 `entries`；只要请求还要求解释、比较、建议或把统计与其他内容综合，就进入 `answer`。显式覆盖继续原样生效。

选择保留两种顶层形态而不是新增 `composite`，因为现有客户端已经能展示结构化 answer points，混合能力属于回答内部依据而不是第三种页面。这样也避免旧客户端无法识别新结果形态。

### 2. quick 才启用复合计划，investigate 暂走旧图

执行顺序调整为：上下文决策 → 结果形态 → 回答模式 → 复合计划。`actual_result_mode=entries` 立即走现有 B1；`actual_answer_mode=investigate` 继续运行现有依据规划与调查；只有 `actual_result_mode=answer && actual_answer_mode=quick` 且特性开关开启时才运行复合计划。auto 回答模式不再依赖预先选出的 `model_first` 来跳过路由，而由现有 answer-mode router 独立判断 quick/investigate。

这样第一阶段能替换最常用且问题明确的单轮路径，同时避免同时重写调查账本、停止条件和恢复协议。代价是 auto 模式多一次回答模式路由；可观测记录会如实反映调用，后续通过真实成本数据再优化。

### 3. `CompositeAnswerPlan v1` 分开表达回答义务和输入请求

新增规划模型输出与服务端规范化模型，建议结构如下：

```text
CompositeAnswerPlan v1
├── requirements[]
│   ├── id                 r1..rN，由服务端重编号
│   ├── order              原始问题的自然回答顺序
│   ├── summary            要回答的内容，不是工具指令
│   ├── kind               explain/retrieve/aggregate/compare/recommend/other
│   └── basis_policy       grove_only/grove_required/model_allowed/external_required
├── statement_message_ids[]
├── retrieval_requests[]
│   ├── id
│   ├── query
│   └── requirement_ids[]
└── structured_requests[]
    ├── id
    ├── entry_set          复用 EntrySetSpec
    ├── outputs[]          复用受限 count/group_count/entries
    └── requirement_ids[]
```

回答义务不是按标点机械拆句。规划提示要求合并同一数据需求，例如“各类型数量和总数”可由一个共享集合的多个输出完成；同一输入请求可以关联多个义务。第一阶段不表达输入请求之间的任意依赖，执行器只使用固定阶段顺序，因此不会与下一 change 的 DAG 职责重叠。

`basis_policy` 是逐义务约束：

- `grove_only`：该义务的事实内容必须来自关联 Grove Evidence 或结构化事实；
- `grove_required`：必须说明 Grove 部分，同时允许模型补充一般解释；
- `model_allowed`：允许模型通用知识直接回答，Grove 输入可选；
- `external_required`：当前没有真实外部材料，最多提供一般框架并保留缺口。

当前话题用户陈述由计划选择服务端给出的消息句柄，但应用再次按 Conversation、范围和上下文链白名单过滤。它们不作为 `basis_policy`，而是可供相关义务使用的非正式前提。

### 4. 原始消息与检索改写同时传递，不能互相覆盖

规划器和最终综合器都必须接收 `current_message` 原文以及独立的 `standalone_query`。原始消息决定回答义务、顺序和自然语言依据限制；独立问题只用于补全指代和生成检索请求。服务端继续确定性识别自然语言 `knowledge_only` 限制，并在规范化时把全部义务收紧为 `grove_only`、删除模型通用知识权限和外部一般回答权限。

“结合我的知识库”表示至少有相关义务需要 Grove，但不等价于“只使用知识库”；规划器可以为概念解释标记 `model_allowed`，为个人记录部分标记 `grove_required`。模型规划失败时不猜测混合意图，而记录 composite planning fallback 并执行旧的安全 basis/quick 路径。

### 5. 服务端规范化模型候选并固化，不执行原始输出

新增独立 planner purpose、prompt version 和配置预算。服务端至少校验：

- requirement、retrieval request、structured request 数量和总 JSON 字节；
- id 唯一且所有关联引用存在；服务端按稳定顺序重编号，忽略模型自报 order 以外的执行优先级；
- kind、basis policy、工具能力、EntrySetSpec 字段和 outputs 均来自闭合枚举；
- query、summary 长度受限，空要求、无消费者请求和重复 requirement id 被拒绝；
- 不允许 Workspace/project/directory/Entry/Source id、SQL、任意运算符、未知工具或写操作；
- `knowledge_only` 不得被任何逐项 policy 放宽；external requirement 不得声称已有外部输入；
- 每项义务至少有可行输入：模型允许、关联检索/结构化请求、合法用户陈述或明确 external gap 之一。

规范化后的 `CompositeAnswerPlan v1` 在工具执行前写入 Run；同一 `client_message_id`、租约恢复和历史读取只能复用该快照。原始模型输出不持久化为可执行数据。

### 6. 固定阶段执行，不实现通用 DAG

第一阶段执行图固定为：

```text
复合计划固化
  → 按计划顺序执行 retrieval_requests
  → 对发现 Entry 读取当前内容并核验 Evidence
  → 按计划顺序执行 structured_requests
  → 生成服务端结构化事实
  → 最终综合与覆盖校验
  → 原子提交 answer、实际依据、覆盖和 Run 终态
```

retrieval request 复用现有 `search_confirmed_knowledge → read_entries → read_evidence`，但在执行快照中保存 request id、关联 requirement ids、实际 Entry/Evidence 句柄、状态和完整性。structured request 直接复用 B1 的 `EntrySetSpec` 规范化与 dispatcher，不再调用第二个结构化查询规划模型；每份请求独立执行，第一阶段不做跨请求合并或并行。

所有工具继续从 Run 注入可信范围。调用前后与终态前检查取消；每完成一个输入请求就持久化有界检查点。恢复时按稳定指纹复用已提交结果，只重放未完成的只读请求。执行快照设置请求数、对象数、Evidence 数、耗时和 JSON 字节总预算。

### 7. 精确结构化结果由服务端生成 `tool_fact`

结构化工具结果先规范化为内部 `CompositeToolFact`：包含不可猜测的 result handle、关联 requirement ids、服务端渲染文本、数值/桶/对象摘要、完整性和边界说明。精确 count/group_count 只有 B1 规则判为 complete 时才使用“共 N 条”等全集措辞；limited/unknown 的事实文本固定说明“本次匹配/当前可确认范围”。

最终模型可以引用 result handle 来解释含义，但不得自行重写服务端事实数字。服务端将 `tool_fact` 作为确定性 answer point 插入对应义务位置，模型只生成解释性 point。这样无需做自然语言数字一致性分析，也能保持旧客户端通过普通 points 展示。

### 8. 回答 point 绑定 requirement，覆盖由服务端派生

`KnowledgeAnswerPointDraft` 增加可选 `requirement_ids` 和内部 `result_handles`；`KnowledgeAnswerPointOut` 追加可选 `requirement_ids`，旧 point 缺失时保持旧行为。复合回答模型接收原始消息、规范化 requirements、允许的用户陈述、已核验 Evidence、tool facts 和执行缺口，必须为每个可回答义务至少生成一个绑定 point。

服务端逐 point 校验：requirement id 必须存在；Evidence 必须来自与该义务关联的 retrieval request；result handle 必须来自关联 structured request；`grove_only` point 没有合法 Grove Evidence/tool fact 时无效；`external_required` 不能标 completed；正文仍不得泄漏句柄。缺少义务时使用 PydanticAI 的一次输出重试要求模型在相同输入上补齐，但不得新增或重跑工具。

终态保存 `CompositeCoverage v1`：每项 requirement 为 `answered`、`partial`、`insufficient` 或 `failed`，记录实际使用的 Evidence/result/user-message 句柄、是否允许并使用模型知识以及缺口说明。整体 answer status 从逐项状态和工具失败派生：全部 answered 才能 completed；有合法部分但存在遗漏或失败为 partial；所有义务均无合法内容为 insufficient；回答模型不可用且无确定性 tool fact 可提交时为 failed。现有 `answer_basis` 从最终合法结果聚合，`planned_basis_strategy` 仅保留兼容诊断值，不再作为复合执行的权威事实。

### 9. API 只追加可选摘要，客户端不展示内部计划

Run 与消息页追加可选的复合计划摘要和覆盖结果，不返回完整 prompt、完整 Entry 或内部推理。摘要只包含 schema 版本、义务标题/顺序、输入类型、逐项状态与实际依据类别。`answer`、`points`、`citations`、`coverage`、`gaps` 和 basis 原字段继续返回；不识别新字段的旧客户端仍能展示服务端拼接文本和 points。

原生端不新增“任务拆解”或工具过程面板，避免把内部编排伪装成模型思维过程。现有 loading/partial/insufficient/fallback 与依据概览继续承担用户反馈；本 change 只补充 API 兼容测试和必要的逐项 gaps 文案测试。

### 10. 使用独立特性开关和显式降级

新增 `KNOWLEDGE_AGENT_COMPOSITE_ANSWER_ENABLED`，默认关闭；同时配置最大 requirements、retrieval requests、structured requests、计划字节、执行结果字节和总耗时。开关关闭时完全执行旧路径。规划模型未配置、超时、非法或持久化失败时记录新的 purpose/fallback 后进入旧 basis/quick；已固化计划后的单个工具失败不整体回退重跑旧 quick，而保留合法结果并形成 partial，防止重复模型/工具调用和语义漂移。

## Risks / Trade-offs

- **[规划 schema 过宽导致模型不稳定]** → 闭合枚举、低数量上限、温度 0、非法即显式 fallback，并用真实复合问法评估而不是增加关键词规则。
- **[第一阶段顺序执行增加延迟]** → 严格限制输入请求数和总耗时，保留阶段耗时；共享/并行优化放到下一 change，避免同时引入调度复杂度。
- **[模型把 Evidence 绑定到错误义务]** → Evidence 与 request/requirement 映射由服务端保存，只接受关联链内句柄；语义正确性仍需评估集和用户验收，不能仅靠句柄证明。
- **[模型通用解释仍可能不准确]** → 只在逐项 policy 允许时使用，Grove/模型依据保持可辨识；实时与高风险材料继续 external gap，不伪造 Citation。
- **[结构化统计被模型改写]** → 数值与完整性文案由服务端 `tool_fact` 生成并确定性插入，模型只能补充解释。
- **[复合计划与旧 basis 字段产生双重事实源]** → 新 Run 以 composite plan/coverage 为权威，旧 `planned_basis_strategy` 只保存聚合兼容值；历史旧 Run 不回填或猜测。
- **[恢复时正式对象已经变化]** → 与 B1 相同，已提交检查点保存生成时有界快照并标识对象状态；未完成读取在重放时重新校验范围和当前对象，最终覆盖如实降级。
- **[客户端看不到内部缺口]** → 服务端继续把逐项缺口投影到现有 `answer.gaps` 和 status；新增摘要为可选增强，不依赖客户端升级才能保持诚实状态。

## Migration Plan

1. 先增加可空的 `composite_answer_plan_json`、`composite_answer_execution_json` 和 `composite_answer_coverage_json` Run 字段及配置，旧记录不回填。
2. 上线 schema、planner、规范化与执行服务，但保持特性开关关闭；运行 SQLite/MySQL 迁移与兼容测试。
3. 接入 quick answer 分支、API 可选字段和 Demo/真实 Provider 可观测，完成后端、原生端兼容与 curl 验收。
4. 在开发环境开启开关，用真实复合问法验证一般解释 + Grove、解释 + 统计、knowledge_only、空结果和降级；原生模拟器/真机手动验收由用户执行。
5. 回滚时先关闭开关恢复旧 basis/quick，再降级迁移移除新增可空列；旧 answer/entries 数据与既有 Run 不受影响。

## Open Questions

- 第一阶段默认上限暂按最多 8 个回答义务、3 个检索请求和 2 个结构化请求设计；实施前通过现有评估夹具与 20 至 30 条真实复合问法校准，若调整只改服务端配置与任务记录，不扩张能力边界。
- `tool_fact` 的中文模板需要在实现时用精确计数、limited 统计、分组和空集合样例校准；它属于协议文案而非视觉重做，原生端保持现有 point 展示。
