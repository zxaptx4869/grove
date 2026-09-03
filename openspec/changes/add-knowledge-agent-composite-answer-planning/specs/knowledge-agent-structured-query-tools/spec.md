## MODIFIED Requirements

### Requirement: 结构化查询计划一次生成并由服务端固化
系统 MUST 在 `actual_result_mode=entries` 且结构化查询能力开启时，使用一次结构化规划调用生成并固化 `StructuredQueryPlan v1`。启用复合回答的 quick Run 可以在已固化的 `CompositeAnswerPlan v1` 中携带一份或多份相同受限 schema 的结构化请求，并直接复用服务端规范化与执行工具，不得再调用第二个结构化规划模型。每份计划或请求 MUST 包含一个共享 `EntrySetSpec` 和受限输出集合，并在工具执行前完成服务端校验、规范化与持久化。模型调用失败、未配置或输出非法结构 MUST 记录 provider、model、fallback、error 与 prompt version，且 MUST NOT 伪装为有效计划。

#### Scenario: entries 合法组合计划
- **WHEN** 用户询问“最近半年的个人经验有多少条，按月分组并列出最近五条”且结果形态为 entries
- **THEN** 结构化规划器可以生成同一集合上的 count、按月 group_count 和按更新时间倒序 entries 输出，服务端校验后固化该计划

#### Scenario: answer 内嵌结构化请求
- **WHEN** 复合 quick 计划需要统计个人经验数量并解释统计结果
- **THEN** composite planner 在规范化计划中提供受限 EntrySetSpec 与输出，服务端直接执行并把工具事实交给综合，不再次调用 structured query planner

#### Scenario: 一份结构化请求服务多个义务
- **WHEN** 总数、按月分组和最近对象分别对应多个回答义务但共享相同筛选集合
- **THEN** 同一结构化请求可以把多个输出关联到这些义务，aggregate 仍直接查询共享集合且 entries limit 不影响精确 count

#### Scenario: entries 计划模型不可用
- **WHEN** 独立 entries 的结构化查询规划模型未配置、超时、失败或返回非法 schema
- **THEN** 系统记录可见降级并按兼容规则执行既有有限语义查找或返回失败，不生成伪统计或精确性承诺

#### Scenario: 复合结构化请求非法
- **WHEN** composite planner 输出的 EntrySetSpec、输出或范围字段不合法
- **THEN** 服务端拒绝整份复合计划并进入显式兼容降级，不静默删除统计条件后继续综合

#### Scenario: 重试不改变首次计划
- **WHEN** 同一 `client_message_id` 被重复提交或 Worker 恢复已经固化结构化/复合计划的 Run
- **THEN** 系统复用首次 Run 与规范化计划，不再次规划或接受重试请求中的不同查询语义
