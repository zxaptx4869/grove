## MODIFIED Requirements

### Requirement: 带引用回答
系统 MUST 返回包含答案文本、引用列表与回答模式/调查摘要的结构化回答；每条事实引用 MUST 指向当前 Run 任一轮由服务端重新核验的 Evidence，并包含 `evidence_id`、`entry_id`、`source_id`、可选 `attachment_id`、Entry/Source 标题、`project_id`/`project_name`/`node_path` 生成时快照与真实原文 `quote`；关键结论 MUST 附有效引用。模型输出的自由 quote、历史 Run 句柄、范围外句柄或未经核验来源 MUST 被丢弃，并据有效引用、覆盖缺口与停止原因调整回答和 Run 状态。

#### Scenario: 回答附真实引用
- **WHEN** 最终回答综合多个已完成调查轮次的证据
- **THEN** 每个关键结论只引用当前 Run 账本中的有效 Evidence，并返回实际模式和调查摘要

#### Scenario: Workspace 引用带项目归属
- **WHEN** 全部知识范围回答引用多个项目的 Evidence
- **THEN** 每条 citation 返回其生成时 project_id/project_name/node_path 快照，客户端无需读取当前对象猜测归属

#### Scenario: 连续回答附本轮真实引用
- **WHEN** 追问回答使用上一主题工作集中的 Entry
- **THEN** 关键结论引用当前 Run 重新生成的 Evidence，而不是复用历史句柄

#### Scenario: 历史对象发生变化
- **WHEN** Citation 对应 Entry、Source、项目名或目录后来变化/删除
- **THEN** 历史 Run 仍返回 Evidence 创建时保存的标题、归属和 quote 快照，不以当前对象重写历史答案

#### Scenario: 丢弃非法引用
- **WHEN** 模型输出其他 Run、范围外、未知或不可引用的 Evidence 句柄
- **THEN** 该引用被丢弃，不进入响应

#### Scenario: 重复引用不重复计数
- **WHEN** 模型多次返回同一个当前 Run Evidence 句柄
- **THEN** 响应只保留一条 citation，coverage 的 Evidence 数量按去重后的有效 citation 计算

#### Scenario: 丢弃部分非法引用
- **WHEN** 模型同时输出当前 Run 有效句柄和历史、范围外或未知句柄
- **THEN** 系统仅保留有效引用并将回答与 Run 标记为 `partial`

#### Scenario: 全部引用失效
- **WHEN** 模型给出事实性回答但所有引用句柄均无效或被丢弃
- **THEN** 系统不得返回 `completed`，而是标记知识/证据不足且 Run 至少为 `partial`

#### Scenario: 模型自由生成 quote
- **WHEN** 模型返回未绑定当前 Run 有效 Evidence 的原文片段
- **THEN** 系统忽略该片段且不将其包装成可信引用

### Requirement: 冲突可见
系统 MUST 在 quick 结果或调查账本中检测到由当前 Run 可核验 Evidence 支持的正式 Entry 相互矛盾时，并列返回冲突摘要、双方 Entry 标题与双方各自完整 citation（含 Evidence、Source、quote 和项目/目录快照），使客户端能分别核验；系统 MUST NOT 替用户裁决。调查控制器识别但缺少双方证据的疑似冲突 MUST 保留为缺口或待核验，不得包装为已证实冲突。

#### Scenario: 调查补查冲突另一方
- **WHEN** 当前账本显示有证据的观点与一个尚缺依据的相反线索且仍有预算
- **THEN** 控制器可提出补查查询，工具结果仍必须形成当前 Run Evidence 才能支持冲突一方

#### Scenario: 返回双边完整证据
- **WHEN** 当前 Run 存在由不同有效 Evidence 支持的矛盾 Entry
- **THEN** 回答返回冲突双方各自的完整 citation，客户端可分别展示 Source 原文而不按 evidence_id 猜测

#### Scenario: 冲突一方证据不可用
- **WHEN** 疑似冲突的一方无法形成可引用 Evidence
- **THEN** 回答将其标记为待核验或未解决缺口，不返回伪造的双边冲突对象

### Requirement: 回答状态与终态覆盖由最终有效 Evidence 决定
系统 MUST 在服务端最终组装回答时，以当前 Run 实际采用且通过校验的 citations、核心问题维度、终态 gaps 与可核验证冲突权威生成 `answer.status`、coverage、gaps 与 conflicts。`completed` MUST 表示核心问题已有充分有效引用支持；`partial` MUST 表示仍有用正文和有效引用、但存在影响完整性的明确缺口；`insufficient` MUST 表示没有足够证据形成有用回答或核心问题基本无法回答。Run 生命周期和 `stop_reason` MUST NOT 直接决定 `answer.status`，搜索前控制器计划 MUST NOT 伪装为终态 coverage/gaps。

#### Scenario: 预算停止但核心回答充分
- **WHEN** 调查因 Evidence 预算停止，但最终有效引用已充分覆盖核心问题且不存在影响回答完整性的缺口
- **THEN** answer.status 为 `completed`，stop_reason 仅在调查摘要解释预算停止

#### Scenario: 有效正文仍有明确缺口
- **WHEN** 最终回答含有效 citations 和有用内容，但某个核心维度或必要条件尚未被当前 Run Evidence 覆盖
- **THEN** answer.status 为 `partial`，终态 gaps 说明实际未覆盖部分

#### Scenario: 只有边缘证据或无证据
- **WHEN** 最终有效 Evidence 只支持边缘信息，或没有足以形成有用回答的有效 citation
- **THEN** answer.status 为 `insufficient`，不得把过程停止原因作为唯一依据

#### Scenario: 部分 citation 校验失效
- **WHEN** 生成后部分引用被丢弃但仍保留足以组成有用答案的其他有效引用
- **THEN** 系统按剩余有效 Evidence 重建 coverage/gaps，并在仍有明确缺口时返回 `partial` 而非 `insufficient`

#### Scenario: 模型未提供终态摘要
- **WHEN** 回答模型未提供 coverage/gaps，或其摘要不能关联最终有效 Evidence 或可验证缺失维度
- **THEN** 服务端使用去重后的 citation、Entry 与账本可验证缺口生成或过滤终态摘要，不以模型默认值宣称完整覆盖或无缺口

### Requirement: 回答正文直接服务问题
系统 MUST 在回答生成 prompt 和结构化输出职责中要求正文首句直接给出事实、推荐、主要差异或操作步骤；正文 MUST NOT 复述用户问题，或使用不增加信息的“关于这个问题”“根据当前已确认知识”“以下是基于正式知识”等开场。范围、来源数、部分结果、预算、轮次、停止原因和 coverage/gaps MUST 由回答卡或调查摘要呈现，不能以长篇重复进入正文。

#### Scenario: 决策问题
- **WHEN** 用户询问在多个方案中如何选择
- **THEN** 正文第一句给出有证据支持的推荐，再说明条件与引用支持

#### Scenario: 对比或操作问题
- **WHEN** 用户请求对比或操作步骤
- **THEN** 正文先给主要差异或可执行步骤，不先复述问题或解释界面状态

#### Scenario: 部分或知识不足结果
- **WHEN** answer.status 为 partial 或 insufficient
- **THEN** 正文仍直接陈述可回答的结论或不足事实，状态、范围和调查限制由结构化区域承担
