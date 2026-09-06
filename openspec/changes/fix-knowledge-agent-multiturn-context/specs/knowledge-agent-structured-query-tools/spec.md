## MODIFIED Requirements

### Requirement: EntrySetSpec 只能表达受限正式知识集合

系统 MUST 使用版本化 `EntrySetSpec` 表达结构化查询集合；集合授权范围 MUST 只来自 Run 固化的 owner、Workspace 和可选项目，模型或客户端 MUST NOT 传入或扩大范围。集合允许可选项目名称筛选，该名称仅在 Run 授权范围内由服务端唯一解析为子集，未知、重名或越界名称 MUST 显式拒绝，不得静默去掉项目条件。集合还允许受控语义查询、`main_type`、`info_nature`、UTC `updated_at` 闭开区间和白名单排序字段，未知字段、运算符、对象标识或 SQL 片段 MUST 被拒绝并留痕。

#### Scenario: 项目范围执行结构化筛选
- **WHEN** 项目范围 Run 的合法计划筛选 `info_nature=experience` 和最近更新时间区间
- **THEN** 系统只查询该项目内满足条件的正式 Entry，不读取同 Workspace 其他项目对象

#### Scenario: 模型尝试指定 Workspace 或项目
- **WHEN** 计划输出包含 Workspace id、项目 id、目录 id、Entry id 或其他授权范围参数
- **THEN** 服务端拒绝非法计划并记录原因，不执行被扩大或改变的范围

#### Scenario: 查询包含未知表达式
- **WHEN** 计划使用未知字段、自由 SQL、正则、任意函数或不受支持的运算符
- **THEN** 服务端不静默删除核心条件或尽量执行，而是将计划判为非法并进入显式降级路径

#### Scenario: Workspace 中指定项目名称
- **WHEN** 用户在 Workspace 对话中指定一个唯一可见项目
- **THEN** 工具只查询该项目子集，Run 的授权范围不变，快照保存实际项目范围

#### Scenario: 全部知识的默认类型
- **WHEN** 用户询问全部知识或正式记录总数，没有明确限定知识类型
- **THEN** 计划不添加 knowledge 单类型条件；只有明确要求知识类型时才限定该类型

### Requirement: 结构化查询计划一次生成并由服务端固化

系统 MUST 在 actual_result_mode=entries 且结构化查询能力开启时，使用一次结构化规划调用生成并固化 StructuredQueryPlan v1。任务状态协议下，该调用 MUST 接收原始消息、选定任务基线及有界实体信息，提出白名单条件与输出增量，由服务端归并并规范化为计划，不得再通过独立改写句重新猜测一份集合。启用复合回答的 quick Run 可以在已固化的 CompositeAnswerPlan v1 中携带一份或多份相同受限 schema 的结构化请求，并直接复用服务端规范化与执行工具，不得再调用第二个结构化规划模型。每份计划或请求 MUST 包含一个共享 EntrySetSpec 和受限输出集合，并在工具执行前完成服务端校验、规范化与持久化。模型调用失败、未配置或输出非法结构 MUST 记录 provider、model、fallback、error 与 prompt version，且 MUST NOT 伪装为有效计划。

#### Scenario: entries 合法组合计划
- **WHEN** 用户询问“最近半年的个人经验有多少条，按月分组并列出最近五条”且结果形态为 entries
- **THEN** 规划器可以生成同一集合上的 count、按月 group_count 和按更新时间倒序 entries 输出，服务端校验后固化该计划

#### Scenario: answer 内嵌结构化请求
- **WHEN** 复合 quick 计划需要统计个人经验数量并解释统计结果
- **THEN** composite planner 根据原始请求和选定任务上下文在规范化计划中提供受限 EntrySetSpec 与输出，服务端直接执行并把工具事实交给综合，不再次调用 structured query planner

#### Scenario: 一份结构化请求服务多个义务
- **WHEN** 总数、按月分组和最近对象分别对应多个回答义务但共享相同筛选集合
- **THEN** 同一结构化请求可以把多个输出关联到这些义务，aggregate 仍直接查询共享集合且 entries limit 不影响精确 count

#### Scenario: entries 计划模型不可用
- **WHEN** 独立 entries 的结构化查询规划模型未配置、超时、失败或返回非法 schema
- **THEN** 系统记录可见降级；旧协议按兼容规则执行既有有限语义查找或返回失败，新任务协议只有能够保持已固化条件和操作时才执行兼容路径，否则停止并说明失败，不生成伪统计或精确性承诺

#### Scenario: 复合结构化请求非法
- **WHEN** composite planner 输出的 EntrySetSpec、输出或范围字段不合法
- **THEN** 服务端拒绝整份复合计划并进入显式兼容降级，不静默删除统计条件后继续综合

#### Scenario: 重试不改变首次计划
- **WHEN** 同一 client_message_id 被重复提交或 Worker 恢复已经固化结构化/复合计划的 Run
- **THEN** 系统复用首次 Run、输入任务版本与规范化计划，不再次规划或接受重试请求中的不同查询语义

### Requirement: aggregate_entries 直接对共享集合执行聚合

`aggregate_entries` MUST 直接对共享集合执行 `count` 或受限 `group_count`，不得从已经被 `entries.limit` 截断的列表反推总数。分组字段 MUST 限定为 `project`、`main_type`、`info_nature` 和 UTC `updated_month`；空 `info_nature` MUST 规范化为 `unspecified`，分组桶数量和序列化体积 MUST 受服务端预算限制。

#### Scenario: 精确计数和列表共享筛选
- **WHEN** 一个无语义条件的计划对相同类型和时间范围请求 count 与最近五条 entries
- **THEN** count 查询覆盖完整授权集合，entries 只返回五条，系统分别表达总数完整性和列表展示上限

#### Scenario: 按月份分组
- **WHEN** 合法计划请求按 `updated_month` 分组计数
- **THEN** SQLite 与 MySQL 8 都按 UTC 年月生成稳定 `YYYY-MM` 桶与计数，并使用确定性桶顺序

#### Scenario: 分组桶达到上限
- **WHEN** group_count 结果超过服务端桶数或字节上限
- **THEN** 系统停止扩张、标记 limited 并显示截断边界，不静默丢桶后仍宣称完整

#### Scenario: 按项目统计
- **WHEN** 用户要求每个项目分别多少条
- **THEN** 系统直接对授权集合按项目聚合，桶含服务端项目标识、名称和数量，包括集合范围内零条项目；同名项目不合并，超预算继续 limited

## ADDED Requirements

### Requirement: 查询条件变化具有明确基线和来源

任务状态协议下，系统 MUST 从经过校验的选定任务版本归并查询变化，保留未改变字段，明确区分替换与撤销；新增和变化条件 MUST 保存用户消息或既有版本来源。关注对象、助手改写或模型推断 MUST NOT 自动升级为用户明确指定的条件。服务端 MUST 拒绝未知字段、非法句柄及同字段冲突操作，且每次 count、分组和列表都执行归并后的同一集合。

#### Scenario: 替换同一字段
- **WHEN** 上轮限定方法类型，本轮要求“换成参数，其他不变”
- **THEN** 类型替换为 parameter，原有项目和时间条件保持，查询中不残留 method

#### Scenario: 只撤销指定条件
- **WHEN** 用户要求去掉时间限制但保留其他条件
- **THEN** 只有时间条件被清除，项目、类型及语义条件保持，并记录撤销来源

#### Scenario: 分组不自动修改集合
- **WHEN** 用户明确要求将当前主题匹配结果按项目分组
- **THEN** 系统保留当前集合并改变输出，不因为出现“分项目”自动删除语义筛选或项目条件

#### Scenario: 明确恢复全部项目统计
- **WHEN** 用户在 Workspace 对话中明确要求回到先前全部项目统计
- **THEN** 系统选择合法的汇总基线并重新执行，不沿用后续单项目筛选；结果摘要表达实际统计口径

### Requirement: 项目实体识别先核实再执行

系统 MUST 在 Run 可信权限内核实用户提及的有界项目名称候选，为规划提供真实匹配和歧义信息；元数据核实 MUST 有数量和体积预算、来源片段及审计，不能读取 Entry 内容或越权项目。项目存在与用户意图 MUST 分别判断；需要项目筛选但匹配未知或重名时 MUST 显式澄清或拒绝，不静默回退为语义搜索或全范围统计。

#### Scenario: 省略项目二字
- **WHEN** 用户在项目统计任务中只说“新疆旅行有多少条”，且该名称唯一匹配可见项目、上下文可确定项目意图
- **THEN** 系统使用真实项目子集做精确统计，不将名称作为 semantic_query

#### Scenario: 同名主题仍可搜索
- **WHEN** 用户明确查询关于某主题的内容，该主题恰好也是可见项目名称
- **THEN** 系统保留主题查询语义，不仅凭项目存在就强制添加项目筛选；结果如为语义集合继续标记 limited 或 unknown

#### Scenario: 预算或名称存在歧义
- **WHEN** 项目名称未知、重名、越权或候选核实超过预算，且无法确定本轮项目子集
- **THEN** 系统具体说明可解决的歧义或限制，不泄露范围外项目存在性，不删除项目条件后继续统计

#### Scenario: 恢复时同名项目已替换
- **WHEN** 任务原先绑定的项目已删除或移出权限范围，另一个项目使用了相同名称
- **THEN** 系统将原目标标为不可用或要求重新选择，不因名称相同就静默查询另一个项目；模型不能提供真实项目标识覆盖绑定
