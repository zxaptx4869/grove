## Context

阶段 A 已允许 Knowledge Agent 在综合回答中选择 Grove、用户当前陈述和模型通用能力，但 `actual_result_mode=entries` 仍使用固定的混合召回、重排和有界 Entry 快照。它适合“找几条相关知识”，不能可靠表示精确筛选、计数、排序、分组或“统计后列出对象”；一旦语义召回达到 top-k，上层也不能把返回数量解释成范围内总数。

本 change 是阶段 B 的第一半：建立一次结构化计划和确定性数据执行面。第二个 change 才让 quick/investigate 在运行中根据中间结果多步选择工具并逐步迁移固定检索 Workflow。现有 Run、`KnowledgeAgentToolCall`、结构化 Entry 快照、原生 Entry 卡和结果形态纠正提供了可复用基础。

约束包括：

- Run 固化的 owner、Workspace 和可选项目是唯一授权范围，模型和客户端不能传入或扩大范围；
- 只查询正式 Entry，不读取 Candidate、Extraction、Draft 或已删除对象；
- SQLite 与 MySQL 8 必须产生一致的过滤、排序、时间边界和分组语义；
- AI 计划只是候选，服务端必须验证；精确结论只能来自确定性全范围执行；
- 结果仍是只读查询快照，不产生 Citation、事实工作集或任何知识写入；
- 旧客户端、旧 Run 和旧 `entry_result_json` 必须继续恢复。

## Goals / Non-Goals

**Goals:**

- 用版本化 `StructuredQueryPlan v1` 和 `EntrySetSpec v1` 表达一次受限查询计划。
- 支持正式 Entry 的结构化过滤、稳定排序、精确计数、受限分组和有界列表。
- 允许多个输出共享同一集合定义，完成“统计 + 分组 + 最近若干条”等常见组合。
- 建立统一的只读工具注册、参数验证、执行和 `KnowledgeAgentToolCall` 审计入口，首批接入 `query_entries`、`aggregate_entries`，并允许既有搜索/读取沿用同一调用协议。
- 扩展 `entries` Run 的持久化、恢复、取消、可观测与原生展示，明确每个结果的完整性和降级。
- 为下一 change 的 quick/investigate 工具规划提供稳定工具契约，不提前引入自主循环。

**Non-Goals:**

- 不实现观察中间结果后再次规划的多轮工具调用。
- 不全面重构 quick/investigate，不移除既有固定搜索、Evidence 与回答流程。
- 不开放任意 SQL、任意字段表达式、目录范围、客户端对象 ID 列表或跨 Workspace 查询。
- 不把语义相关性集合上的计数描述成范围内精确总数。
- 不建设通用报表、可视化分析器、导出或无限分页。
- 不涉及 `prepare_operation`、Candidate、Entry Revision 或任何正式知识写入。

## Decisions

### 1. 采用一次结构化计划，而不是在本 change 引入 Agent 循环

`actual_result_mode=entries` 确定后，新增一次 `structured_query_plan` 模型调用。模型只能输出版本化计划：一个共享 `EntrySetSpec` 和一至多个允许的输出请求。服务端校验成功后按固定顺序执行，不把第一个工具结果重新发给模型决定下一步。

这样可以覆盖高价值的筛选、统计和列表组合，同时把循环预算、逐步恢复和控制器复杂度留给 B2。相比继续增加“计数问题”“排序问题”等顶层路由，结构化计划以同一契约组合求解；相比立即采用通用工具循环，失败面和延迟更可控。

计划失败、模型未配置或输出非法时，服务端记录 provider/model/fallback/error，并回退现有结构化语义查找。回退结果不得包含伪造聚合，也不得宣称精确完成。

### 2. `EntrySetSpec v1` 只开放可跨数据库确定执行的白名单字段

第一版集合定义包含：

- 隐式 `scope`：只从 Run 读取，不出现在模型可控参数中；
- 可选 `semantic_query`：复用现有混合召回，形成有界相关集合；
- `main_types`：`knowledge / method / parameter / reminder` 的受控集合；
- `info_natures`：`fact / experience / advice / speculation / other / unspecified` 的受控集合；
- `updated_at`：UTC 的闭开时间区间 `[from, to)`；
- `sort`：`relevance`、`updated_at` 或 `created_at`，方向受限为升序/降序；所有非唯一排序最后追加 Entry id 作为稳定 tie-breaker。

不开放自由字段名、自由运算符、目录 id、项目 id、Entry id、Source 字段、任意正则或 SQL 片段。Workspace 对话若需要缩小到具体项目，继续使用既有对话范围选择；模型不能通过集合参数自行切换项目。

`semantic_query` 与结构化条件可以组合，但集合完整性继承语义召回的有限性。没有 `semantic_query` 时，结构化条件直接在授权范围内执行，可以在数据库正常完成时证明集合完整。

备选方案是支持标题/正文 `contains` 作为“精确文本过滤”。SQLite 与 MySQL 8 在大小写、排序规则和 Unicode 匹配上的默认语义不同，首版不把它作为精确原语；文本主题继续走语义查询并诚实标记有限。

### 3. 输出操作共享集合，聚合不从已经截断的列表反推

`StructuredQueryPlan v1` 允许以下输出：

- `entries`：按集合排序返回有界 Entry 快照；
- `count`：统计集合总数；
- `group_count`：按 `main_type`、`info_nature` 或 `updated_month` 分组计数。

同一计划最多包含服务端设定数量的输出，每种输出最多一次。`count` 和 `group_count` 必须直接针对集合查询执行，不能对 `entries.limit` 截断后的列表计数。`updated_month` 使用 UTC 年月键，服务端通过 SQLAlchemy 方言兼容表达式执行并统一序列化为 `YYYY-MM`；空 `info_nature` 统一为 `unspecified`。

计划可表达“统计 + 分组 + 最近 5 条”，但不能表达任意依赖图、嵌套子查询或上一步结果驱动的下一步。列表上限、分组桶上限、计划输出数、JSON 字节数和执行超时全部由服务端配置控制，模型请求只能在上限内收紧。

### 4. 精确性按共享集合与具体输出共同派生

每个结构化输出都保存 `complete / limited / unknown`：

- 无语义条件、授权范围完成扫描、无超时或工具异常时，`count`、完整分组和集合耗尽状态可为 `complete`；
- 含 `semantic_query`、候选/top-k/持久化上限截断或明确预算停止时为 `limited`；
- 执行发生部分失败、对象状态在查询期间无法确定或后端不能证明覆盖时为 `unknown`；
- `entries` 列表即使只展示前 N 条，也可以同时表达“集合统计完整、展示列表有界”，不能用一个含混布尔值覆盖二者。

界面文案从结构化状态生成。只有 `complete` 的 count 才显示“共 N 条”；有限语义集合显示“本次匹配到 N 条”或等价边界，不显示“全部”。正常空集合不是 fallback。

### 5. 复用 Run JSON 快照与现有工具调用表，不新建通用账本体系

Run 追加可空 `structured_query_plan_json`，保存通过服务端校验、规范化后的计划快照和 prompt 版本。`entry_result_json` 升级为向后兼容的 v2：保留 Entry items 和分页字段，新增集合摘要、排序、聚合块、各输出完整性与计划/执行警告。旧 v1 快照按既有协议读取，不猜测计划或聚合结果。

每次 `query_entries`、`aggregate_entries` 继续写入现有 `KnowledgeAgentToolCall`，保存工具名、版本、脱敏规范化参数摘要、结果数量/桶数、完整性、状态、耗时与错误；不复制完整 Entry、prompt 或无限分组内容。模型计划调用继续写入 `KnowledgeAgentModelInvocation`，purpose 固定为 `structured_query_plan`。

相比新建独立通用账本表，此方案复用已经验证的 Run 归属、Workspace 隔离、调用顺序与可观测 API，减少迁移和重复概念。若 B2 需要跨轮次依赖图，再基于实际需求扩展调用关联字段。

### 6. 统一执行入口由应用控制工具注册和可信上下文

新增只读工具注册表/dispatcher，但首版只执行应用代码提供的白名单工具。调用输入由“Run 可信上下文 + 已校验参数”组成：dispatcher 不接受模型提供 owner、Workspace、project 或数据库会话标识；每个工具内部仍重复范围谓词，形成纵深防护。

`query_entries` 返回有界对象句柄和快照字段，`aggregate_entries` 返回标量或受限桶；工具结果不是 Citation，也不进入回答工作集。既有 `search_knowledge`、`read_entries`、`read_evidence` 本 change 只适配相同的调用状态和审计结构，不改变其发现集合与 Evidence 授权逻辑。

工具状态限定为 `completed / empty / limited / partial / denied / error / cancelled`。未知工具、未知字段、超预算和越权参数在模型调用后由应用拒绝并留痕，不尝试“尽量执行”或静默删掉会改变语义的核心条件。

### 7. 崩溃恢复重放已固化计划，终态仍原子提交

计划校验后先提交 `structured_query_plan_json` 和模型调用审计，再执行确定性工具。Worker 恢复时：

1. 已有合法计划则直接复用，不再次调用模型；
2. 已提交成功工具调用可以按调用指纹复用其有界结构化结果，未完成调用按幂等查询重放；
3. 最终 v2 快照、助手兼容文本、Run 终态和活动槽在一个事务中提交；
4. 取消检查位于计划前后、每个工具前后和终态提交前，取消后的迟到结果不能形成正常快照。

数据库查询本身只读，重放不会修改 Entry。调用指纹包含 Run、工具版本和规范化参数，不跨 Run 复用，也不因后来消息改变原计划。

### 8. 原生端在 `entries` 结果内展示统计，不新增顶层结果形态

继续使用 `actual_result_mode=entries`，避免再增加一套结果路由和纠正动作。v2 结果按以下顺序展示：范围/筛选摘要 → 精确性提示 → count/group 块 → 排序与 Entry 卡 → 分页/警告。纯列表查询维持现有布局；旧 v1 快照维持当前“找到 N 条相关知识”。

统计块是应用根据服务端结构化数据渲染的对象结果，不是 AI 综合回答、Citation 或正式 Entry。分组桶按服务端稳定顺序显示并受上限控制；长列表继续使用持久化快照分页，打开卡片时读取当前 Entry 并提示变化。

## Risks / Trade-offs

- [模型经常生成非法或过宽计划] → 使用严格 schema、枚举和数量预算；拒绝改变语义的未知条件，显式回退旧查找并建立代表性评估集。
- [语义主题与“精确数量”被用户混为一谈] → 精确性在每个输出上结构化返回；含语义集合时禁止“共 N 条/全部”等文案。
- [SQLite 与 MySQL 8 的时间分组或空值排序不一致] → 时间统一为 UTC、显式 NULL 归一化、追加 id tie-breaker，并建立双方言 SQL/迁移测试。
- [全范围精确聚合随 Entry 增长变慢] → 第一版只开放索引友好的等值和时间范围过滤，限制分组字段、执行超时和桶数；评测后再决定索引。
- [在 B1 引入 dispatcher 但只有少量工具，抽象可能过早] → 接口只覆盖可信上下文、版本化参数、结果状态和审计四个已确定共性，不提前设计 B2 的循环协议。
- [Run JSON v2 变大或破坏旧客户端] → 限制列表、桶数与字节数；新增字段可选，旧 v1 解析保留，分页只读取同一快照。
- [恢复时复用工具结果与当前 Entry 状态不一致] → 结果明确是 Run 生成时快照；详情始终重新鉴权并读取当前对象，恢复只重建同一历史结果，不冒充当前状态。

## Migration Plan

1. 增加可空 Run 计划字段及向后兼容 schema，迁移同时验证 SQLite 与 MySQL 8；不回填旧 Run。
2. 在新特性开关关闭状态部署后端执行器、计划器与 v2 API；旧 `entries` 执行图继续工作。
3. 部署能解析 v1/v2 的原生客户端；缺少筛选或聚合字段时保持既有 Entry 结果展示。
4. 完成确定性服务测试、Runner 恢复/取消测试、API/原生兼容测试、代表性评估和手动走查后，小范围开启结构化查询开关。
5. 观察计划成功率、fallback、查询耗时、完整性分布、桶截断和纠正结果形态行为；异常时关闭新开关，回到旧结构化查找。
6. 回滚不删除新增可空字段或历史 v2 快照；旧客户端、旧 Run 和正式 Entry 不受影响。

## Open Questions

- 第一版是否需要为结构化字段补充组合索引，应根据真实 Explain/基准结果决定，不能只凭预期提前增加写入成本。
- `updated_month` 在用户本地时区还是 UTC 分组：本 change 默认按 UTC 保持跨端确定性；若真实体验中跨月边界明显，再单独设计 Workspace 时区能力。
