## MODIFIED Requirements

### Requirement: 问答范围与 Workspace 隔离
系统 MUST 支持当前 Workspace「全部知识」与具体项目两种用户可选问答范围，不再提供目录节点级范围；问答 MUST 只读取 Run 固化范围内已确认的正式 Entry；越权 Workspace、项目、对话或 Run MUST 失败（404），不暴露范围外数据。

#### Scenario: Workspace 阅读
- **WHEN** 用户在「全部知识」范围发起问答
- **THEN** 回答可基于当前 Workspace 内各项目的已确认 Entry，并显示引用的项目归属

#### Scenario: 项目阅读
- **WHEN** 用户在具体项目范围发起问答
- **THEN** 回答只基于该项目的已确认 Entry

#### Scenario: 目录不作为用户范围
- **WHEN** 用户从 Web 或原生 App 选择知识问答范围
- **THEN** 可选项只包含「全部知识」与项目，目录仅作为检索和引用定位信息

#### Scenario: 越权对象 404
- **WHEN** 用户请求不属于当前 Workspace 或当前用户的项目、对话或 Run
- **THEN** 请求失败（404），不返回任何相关数据

### Requirement: 证据召回复用语义检索
系统 MUST 在持久化 Agent Run 中通过受可信范围约束的知识工具复用语义检索混合召回与文本模型语义重排，按用户问题选取最多 15 条已确认 Entry 作为回答上下文；embedding 未配置或失败时 MUST 显式降级为确定性召回；重排模型未配置或调用失败时 MUST 使用确定性召回顺序并记录该阶段降级，不得静默调用外部服务。

#### Scenario: 按问题召回上下文
- **WHEN** Run 搜索用户问题且 embedding 与重排可用
- **THEN** 系统在固化范围内合并确定性与 embedding 召回，并将语义重排后的相关正式 Entry 作为回答上下文

#### Scenario: embedding 降级
- **WHEN** 当前 Workspace 未配置 embedding 或编码失败
- **THEN** 系统使用确定性召回结果并在 embedding 阶段记录降级，不中断后续证据读取

#### Scenario: 重排模型降级
- **WHEN** 文本重排模型未配置或调用失败
- **THEN** 系统使用确定性召回顺序并在重排阶段记录降级，不把该阶段标记为正常

### Requirement: 带引用回答
系统 MUST 返回包含答案文本与引用列表的结构化回答；每条引用 MUST 指向当前 Run 中由服务端核验的 Evidence，并包含 `evidence_id`、`entry_id`、`source_id`、可选 `attachment_id` 与真实原文 `quote`；关键结论 MUST 附有效引用；模型输出的自由 quote、范围外句柄或未经核验来源 MUST 被丢弃。

#### Scenario: 回答附真实引用
- **WHEN** 回答中包含基于已确认 Entry 的关键结论
- **THEN** 该结论引用当前 Run 的 Evidence，且 `quote` 是实际 Source Attachment 中核验过的原文

#### Scenario: 丢弃非法引用
- **WHEN** 模型输出其他 Run、范围外、未知或不可引用的 Evidence 句柄
- **THEN** 该引用被丢弃，不进入响应

#### Scenario: 模型自由生成 quote
- **WHEN** 模型返回未绑定有效 Evidence 的原文片段
- **THEN** 系统忽略该片段且不将其包装成可信引用

### Requirement: 知识不足可见
系统 MUST 在当前范围内没有足够正式 Entry 或没有可核验 Evidence 时明确说明知识不足，不得用模型自身知识悄悄补齐；关键结论无法获得有效引用时 MUST 将 Run 标为 `partial` 或将回答标记 `insufficient`。

#### Scenario: 没有相关正式知识
- **WHEN** 当前问答范围内没有足以回答问题的已确认 Entry
- **THEN** 回答明确说明知识不足、不编造内容并标记 `insufficient`

#### Scenario: 有 Entry 但无可核验证据
- **WHEN** 召回到相关 Entry 但其来源原文无法读取或核验
- **THEN** 系统说明证据不足且不以未经核验的引用支持确定性结论

### Requirement: 冲突可见
系统 MUST 在检测到当前范围内有可核验 Evidence 支持的正式 Entry 相互矛盾时并列展示冲突双方、各自观点与各自 Evidence，不替用户裁决；缺少来源证据的疑似冲突 MUST 标记为待核验。

#### Scenario: 展示有证据的冲突
- **WHEN** 当前范围内存在由不同有效 Evidence 支持的矛盾 Entry
- **THEN** 回答并列展示冲突双方、观点和各自引用

#### Scenario: 冲突一方证据不可用
- **WHEN** 疑似冲突的一方无法形成可引用 Evidence
- **THEN** 回答将其标记为待核验而不把双方包装成同等可信结论

### Requirement: 可观测性
系统 MUST 对一次问答的 embedding、重排、工具和回答阶段分别记录 provider、model、fallback 状态、error 与耗时，并在 Run 响应中汇总降级；未配置密钥或任一模型调用失败 MUST 明确标记对应阶段和原因，禁止静默降级。

#### Scenario: 正常回答记录各阶段来源
- **WHEN** 问答各 AI 阶段均由真实模型完成
- **THEN** 每个模型阶段记录实际 provider/model 与 `is_fallback=false`，Run 不显示降级

#### Scenario: 单阶段降级可识别
- **WHEN** embedding、重排或回答任一阶段降级或失败
- **THEN** 对应阶段记录 `is_fallback=true` 或失败原因，Run 汇总中可识别受影响阶段

## REMOVED Requirements

### Requirement: 回答类型推荐
**Reason**: 首个知识 Agent change 专注只读、可信的首次问答底座，不再把“回答是否适合保存”混入阅读响应契约；知识写入与候选类型由后续独立写工具 change 定义。

**Migration**: 旧 Reader 兼容 API 在 Web 迁移前可以继续返回 `main_type` 与 `info_nature`，现有回答转候选接口保持可用；新知识 Agent API 不依赖这两个字段。

### Requirement: 保存建议
**Reason**: 本 change 明确不提供保存回答或写知识工具，`save_recommended` 不能作为只读 Agent 的核心承诺。

**Migration**: 旧 Reader 兼容 API 与现有 `answer-to-candidate` 链路暂时保持原行为；后续新增经用户确认的知识写工具时重新定义保存触发和候选契约。
