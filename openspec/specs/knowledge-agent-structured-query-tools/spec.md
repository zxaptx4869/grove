# knowledge-agent-structured-query-tools Specification

## Purpose
TBD - created by archiving change add-knowledge-agent-structured-query-tools. Update Purpose after archive.
## Requirements
### Requirement: EntrySetSpec 只能表达受限正式知识集合
系统 MUST 使用版本化 `EntrySetSpec` 表达结构化查询集合；集合授权范围 MUST 只来自 Run 固化的 owner、Workspace 和可选项目，模型或客户端 MUST NOT 传入或扩大范围。第一版只允许受控语义查询、`main_type`、`info_nature`、UTC `updated_at` 闭开区间和白名单排序字段，未知字段、运算符、对象标识或 SQL 片段 MUST 被拒绝并留痕。

#### Scenario: 项目范围执行结构化筛选
- **WHEN** 项目范围 Run 的合法计划筛选 `info_nature=experience` 和最近更新时间区间
- **THEN** 系统只查询该项目内满足条件的正式 Entry，不读取同 Workspace 其他项目对象

#### Scenario: 模型尝试指定 Workspace 或项目
- **WHEN** 计划输出包含 Workspace id、项目 id、目录 id、Entry id 或其他授权范围参数
- **THEN** 服务端拒绝非法计划并记录原因，不执行被扩大或改变的范围

#### Scenario: 查询包含未知表达式
- **WHEN** 计划使用未知字段、自由 SQL、正则、任意函数或不受支持的运算符
- **THEN** 服务端不静默删除核心条件或尽量执行，而是将计划判为非法并进入显式降级路径

### Requirement: 结构化查询计划一次生成并由服务端固化
系统 MUST 在 `actual_result_mode=entries` 且结构化查询能力开启时，使用一次结构化规划调用生成 `StructuredQueryPlan v1`；计划 MUST 包含一个共享 `EntrySetSpec` 和受限输出集合，并在工具执行前完成服务端校验、规范化与持久化。模型调用失败、未配置或输出非法结构 MUST 记录 provider、model、fallback、error 与 prompt version，且 MUST NOT 伪装为有效计划。

#### Scenario: 合法组合计划
- **WHEN** 用户询问“最近半年的个人经验有多少条，按月分组并列出最近五条”且结果形态为 entries
- **THEN** 规划器可以生成同一集合上的 count、按月 group_count 和按更新时间倒序 entries 输出，服务端校验后固化该计划

#### Scenario: 计划模型不可用
- **WHEN** 结构化查询规划模型未配置、超时、失败或返回非法 schema
- **THEN** 系统记录可见降级并按兼容规则执行既有有限语义查找或返回失败，不生成伪统计或精确性承诺

#### Scenario: 重试不改变首次计划
- **WHEN** 同一 `client_message_id` 被重复提交或 Worker 恢复已经固化计划的 Run
- **THEN** 系统复用首次 Run 与规范化计划，不再次规划或接受重试请求中的不同查询语义

### Requirement: query_entries 确定性返回有界 Entry 快照
`query_entries` MUST 对经过校验的集合应用白名单排序并返回有界正式 Entry 快照；`relevance` 只能用于包含语义查询的集合，`updated_at` 和 `created_at` 排序 MUST 追加 Entry id 作为稳定 tie-breaker。返回项 MUST 继续包含生成时 Entry、项目、目录、类型、更新时间、来源数量和指纹等受控字段，不得包含 Candidate、完整 Source 原文或模型编造的匹配理由。

#### Scenario: 按更新时间列出最近五条
- **WHEN** 合法计划请求对完整结构化集合按 `updated_at desc` 返回五条
- **THEN** 工具使用稳定排序返回最多五个 Entry 快照，相同更新时间按 Entry id 确定顺序

#### Scenario: 语义集合按相关性排序
- **WHEN** 集合包含语义查询并请求 relevance 排序
- **THEN** 工具复用受控召回与重排，仅返回合法候选并把集合完整性标为 limited 或 unknown

#### Scenario: 非语义集合请求相关性排序
- **WHEN** 没有 semantic_query 的计划请求 relevance 排序
- **THEN** 服务端拒绝该输出参数，不用隐藏默认顺序伪装成功

### Requirement: aggregate_entries 直接对共享集合执行聚合
`aggregate_entries` MUST 直接对共享集合执行 `count` 或受限 `group_count`，不得从已经被 `entries.limit` 截断的列表反推总数。第一版分组字段 MUST 限定为 `main_type`、`info_nature` 和 UTC `updated_month`；空 `info_nature` MUST 规范化为 `unspecified`，分组桶数量和序列化体积 MUST 受服务端预算限制。

#### Scenario: 精确计数和列表共享筛选
- **WHEN** 一个无语义条件的计划对相同类型和时间范围请求 count 与最近五条 entries
- **THEN** count 查询覆盖完整授权集合，entries 只返回五条，系统分别表达总数完整性和列表展示上限

#### Scenario: 按月份分组
- **WHEN** 合法计划请求按 `updated_month` 分组计数
- **THEN** SQLite 与 MySQL 8 都按 UTC 年月生成稳定 `YYYY-MM` 桶与计数，并使用确定性桶顺序

#### Scenario: 分组桶达到上限
- **WHEN** group_count 结果超过服务端桶数或字节上限
- **THEN** 系统停止扩张、标记 limited 并显示截断边界，不静默丢桶后仍宣称完整

### Requirement: 每个结构化输出独立表达完整性
系统 MUST 为共享集合及 count、group_count、entries 各输出保存 `complete`、`limited` 或 `unknown` 完整性。只有不含语义查询、授权范围查询完整结束且没有预算截断或异常时，系统才能把范围计数或分组标记为 complete；含语义召回、top-k、超时或部分失败的结果 MUST NOT 使用“全部”“共 N 条”等精确全集语义。

#### Scenario: 纯结构化集合精确完成
- **WHEN** 无语义条件的类型与时间筛选在授权范围内正常完成
- **THEN** count 和未截断分组可以标记 complete，界面可以显示精确总数

#### Scenario: 语义集合返回统计
- **WHEN** 集合使用 semantic_query 后对候选结果计数或分组
- **THEN** 对应输出标记 limited 或 unknown，并说明统计只覆盖本次匹配集合而非范围内所有相关知识

#### Scenario: 正常空集合
- **WHEN** 完整结构化查询正常完成且没有满足条件的 Entry
- **THEN** 系统返回 complete 的零计数和空列表，工具状态为 empty，不记录为 AI fallback

#### Scenario: 工具部分失败
- **WHEN** 查询期间部分对象不可用、超时或后端无法证明覆盖
- **THEN** 受影响输出标记 unknown 或 partial，保留合法结果且不得升级为 complete

### Requirement: 只读工具执行入口统一验证预算与审计
系统 MUST 通过应用控制的白名单执行入口调用 `query_entries` 和 `aggregate_entries`；执行入口 MUST 注入 Run 可信上下文、校验工具版本与参数、限制调用数/列表数/桶数/耗时/JSON 字节数，并按顺序记录工具名、脱敏参数摘要、结果摘要、完整性、状态、耗时和错误。模型不能注册工具、传入数据库会话或覆盖预算。

#### Scenario: 两个工具正常执行
- **WHEN** 合法计划请求一次 aggregate_entries 和一次 query_entries
- **THEN** 执行入口按固定顺序运行并分别保存 completed 或 empty 调用记录及实际预算消耗

#### Scenario: 未知工具或超预算调用
- **WHEN** 计划请求未注册工具、重复输出超过允许次数或把 limit 设置为服务端上限之外
- **THEN** 服务端拒绝计划或调用并记录 denied，不静默扩大预算或执行未知能力

#### Scenario: 审计内容最小化
- **WHEN** 查询命中长正文或大量分组
- **THEN** 工具调用记录只保存有界对象句柄、数量、桶摘要和执行元数据，不复制完整 Entry、Source 原文或原始 prompt

### Requirement: 查询工具不产生知识写入与事实工作集
结构化查询计划、工具调用、统计结果和 Entry 快照 MUST 只属于当前只读 Run；它们 MUST NOT 创建或修改 Source、Candidate、Entry、EntryVersion、目录或 pending 对象，也 MUST NOT 因查询命中自动推进 Conversation 事实工作集。统计结果不是 Citation，模型计划不是正式知识。

#### Scenario: 统计并列出对象
- **WHEN** Run 成功返回 count、group_count 和若干 Entry 卡
- **THEN** 系统只保存查询计划、调用审计和结果快照，不创建知识对象或工作集版本

#### Scenario: 查询文字包含修改意图
- **WHEN** 普通 entries 请求文本中夹带“把这些都改成方法”等写入意图但未进入未来结构化操作协议
- **THEN** 本 change 的工具只执行允许的只读查询或要求澄清，不修改任何 Entry

