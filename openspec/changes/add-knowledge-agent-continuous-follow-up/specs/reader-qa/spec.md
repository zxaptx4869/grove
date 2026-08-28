## MODIFIED Requirements

### Requirement: 证据召回复用语义检索
系统 MUST 在持久化 Agent Run 中通过受可信范围约束的知识工具复用语义检索混合召回与文本模型语义重排；新话题按独立查询召回，继续追问 MUST 将复验有效的输入工作集种子与当前独立查询的新召回去重并统一重排，最终选取最多 15 条已确认 Entry 作为回答上下文；embedding 或重排降级 MUST 分阶段记录，不得静默调用外部服务。

#### Scenario: 新话题按当前问题召回
- **WHEN** Run 决策为新话题且 embedding 与重排可用
- **THEN** 系统在固化范围内按当前独立查询召回和重排相关正式 Entry

#### Scenario: 追问合并工作集与新召回
- **WHEN** Run 决策为继续当前主题
- **THEN** 系统合并复验有效的工作集 Entry 与新召回项，并按独立查询统一重排为回答上下文

#### Scenario: embedding 降级
- **WHEN** 当前 Workspace 未配置 embedding 或编码失败
- **THEN** 系统使用确定性召回结果并在 embedding 阶段记录降级，不中断后续证据读取

#### Scenario: 重排模型降级
- **WHEN** 文本重排模型未配置或调用失败
- **THEN** 系统使用确定性合并顺序并在重排阶段记录降级，不把该阶段标记为正常

### Requirement: 带引用回答
系统 MUST 返回包含答案文本与引用列表的结构化回答；每条事实引用 MUST 指向当前 Run 中由服务端重新核验的 Evidence，并包含 `evidence_id`、`entry_id`、`source_id`、可选 `attachment_id` 与真实原文 `quote`；关键结论 MUST 附有效引用；模型输出的自由 quote、历史 Run 句柄、范围外句柄或未经核验来源 MUST 被丢弃，并据有效引用结果调整回答与 Run 状态。

#### Scenario: 连续回答附本轮真实引用
- **WHEN** 追问回答使用上一主题工作集中的 Entry
- **THEN** 关键结论引用当前 Run 重新生成的 Evidence，而不是复用历史句柄

#### Scenario: 丢弃部分非法引用
- **WHEN** 模型同时输出当前 Run 有效句柄和历史、范围外或未知句柄
- **THEN** 系统仅保留有效引用并将回答与 Run 标记为 `partial`

#### Scenario: 全部引用失效
- **WHEN** 模型给出事实性回答但所有引用句柄均无效或被丢弃
- **THEN** 系统不得返回 `completed`，而是标记知识/证据不足且 Run 至少为 `partial`

#### Scenario: 模型自由生成 quote
- **WHEN** 模型返回未绑定当前 Run 有效 Evidence 的原文片段
- **THEN** 系统忽略该片段且不将其包装成可信引用

### Requirement: 知识不足可见
系统 MUST 在当前范围内没有足够正式 Entry、工作集种子已失效或没有本 Run 可核验 Evidence 时明确说明知识不足，不得用历史助手回答或模型自身知识悄悄补齐；关键结论无法获得有效引用时 MUST 将 Run 标为 `partial` 或将回答标记 `insufficient`。

#### Scenario: 没有相关正式知识
- **WHEN** 当前范围内的新召回与复验工作集都没有足以回答问题的正式 Entry
- **THEN** 回答明确说明知识不足、不编造内容并标记 `insufficient`

#### Scenario: 有 Entry 但无本轮可核验证据
- **WHEN** 召回或工作集包含相关 Entry 但其当前来源原文无法读取或核验
- **THEN** 系统说明证据不足且不以历史 Evidence 或未经核验引用支持确定性结论

### Requirement: 可观测性
系统 MUST 对一次问答的上下文决策/改写、embedding、重排、工具和回答阶段分别记录 provider、model、fallback 状态、error 与耗时，并在 Run 响应中汇总降级或异常；未配置密钥、任一模型调用失败、工具部分失败或引用校验降级 MUST 明确标记对应阶段和原因，禁止静默降级。

#### Scenario: 正常连续回答记录各阶段来源
- **WHEN** 上下文决策及问答各 AI 阶段均由真实模型完成且引用有效
- **THEN** 每个模型阶段记录实际 provider/model 与 `is_fallback=false`，Run 不显示降级

#### Scenario: 单阶段降级可识别
- **WHEN** 上下文决策、embedding、重排、工具、引用校验或回答任一阶段降级或失败
- **THEN** 对应阶段记录 fallback 或失败原因，Run 汇总中可识别受影响阶段

#### Scenario: 正常空搜索不误报
- **WHEN** 搜索成功完成但没有相关正式 Entry
- **THEN** 系统记录知识不足，不把正常空结果标成模型 fallback
