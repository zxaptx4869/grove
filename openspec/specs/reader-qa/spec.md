# reader-qa Specification

## Purpose
基于已确认 Entry 提供 Workspace/项目范围的带引用问答；问答由持久化知识 Agent Run 生成，引用经服务端核验 Evidence 校验后返回，冲突与知识不足可见。
## Requirements
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
系统 MUST 在持久化 Agent Run 中通过受可信范围约束的知识工具复用语义检索混合召回与文本模型语义重排；quick 模式按一个独立查询完成单轮召回，investigate 模式可在预算内按多轮不同查询召回并将结果加入 Run 账本；继续追问 MUST 将复验有效的输入工作集种子与当前 Run 新召回去重统一重排。单次回答上下文最多包含 15 条已确认 Entry，调查账本不同 Entry 总量另受服务端预算限制；embedding 或重排降级 MUST 分阶段、分轮次记录，不得静默调用外部服务。

#### Scenario: 按问题召回上下文
- **WHEN** actual mode 为 quick 且 embedding 与重排可用
- **THEN** 系统在固化范围内按当前独立查询召回和重排相关正式 Entry

#### Scenario: 新话题按当前问题召回
- **WHEN** Run 决策为新话题且 embedding 与重排可用
- **THEN** 系统在固化范围内按当前独立查询召回和重排相关正式 Entry

#### Scenario: 调查按新缺口补查
- **WHEN** 调查控制器基于当前账本提出合法新查询
- **THEN** 系统在相同固化范围执行混合召回、记录轮次归属并把去重后的新 Entry 加入账本

#### Scenario: 追问合并工作集与新召回
- **WHEN** Run 决策为继续当前主题
- **THEN** 系统合并复验有效的工作集 Entry 与本 Run 新召回项，并按当前独立问题统一重排为回答上下文

#### Scenario: 最终上下文截断
- **WHEN** 调查账本中的不同 Entry 超过最终回答上下文上限
- **THEN** 系统按与问题和覆盖目标的统一重排结果确定性选取最多 15 条，而不把全部搜索结果塞入模型

#### Scenario: embedding 降级
- **WHEN** 某轮当前 Workspace 未配置 embedding 或编码失败
- **THEN** 系统使用确定性召回结果并在对应轮次 embedding 阶段记录降级，不中断后续证据读取

#### Scenario: 重排模型降级
- **WHEN** 某轮文本重排模型未配置或调用失败
- **THEN** 系统使用确定性合并顺序并在对应轮次重排阶段记录降级，不把该阶段标记为正常

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

### Requirement: 知识不足可见
系统 MUST 在当前范围内没有足够正式 Entry、工作集种子已失效、调查达到上限仍有未覆盖部分或没有当前 Run 可核验 Evidence 时明确说明知识不足和未解决缺口，不得用历史助手回答或模型自身知识悄悄补齐；关键结论无法获得有效引用时 MUST 将 Run 标为 `partial` 或将回答标记 `insufficient`。

#### Scenario: 没有相关正式知识
- **WHEN** quick 或调查的新召回与复验工作集都没有足以回答问题的正式 Entry
- **THEN** 回答明确说明知识不足、不编造内容并标记 `insufficient`

#### Scenario: 有 Entry 但无可核验证据
- **WHEN** 召回到相关 Entry 但其来源原文无法读取或核验
- **THEN** 系统说明证据不足且不以未经核验的引用支持确定性结论

#### Scenario: 达到预算仍有缺口
- **WHEN** 调查因轮次或其他预算停止且仍存在未覆盖方面
- **THEN** 回答列出已有证据支持的部分与未解决缺口，并返回稳定停止原因

#### Scenario: 有 Entry 但无本轮可核验证据
- **WHEN** 召回或工作集包含相关 Entry 但其当前来源原文无法读取或核验
- **THEN** 系统说明证据不足且不以历史 Evidence 或未经核验引用支持确定性结论

#### Scenario: 工作集证据已失效
- **WHEN** 工作集包含相关 Entry 但其当前来源原文无法读取或核验
- **THEN** 系统说明证据不足且不以历史 Evidence 或未经核验引用支持确定性结论

### Requirement: 冲突可见
系统 MUST 在 quick 结果或调查账本中检测到由当前 Run 可核验 Evidence 支持的正式 Entry 相互矛盾时，并列返回冲突摘要、双方 Entry 标题与双方各自完整 citation（含 Evidence、Source、quote 和项目/目录快照），使客户端能分别核验；系统 MUST NOT 替用户裁决。调查控制器识别但缺少双方证据的疑似冲突 MUST 保留为缺口或待核验，不得包装为已证实冲突。

#### Scenario: 调查补查冲突另一方
- **WHEN** 当前账本显示有证据的观点与一个尚缺依据的相反线索且仍有预算
- **THEN** 控制器可提出补查查询，工具结果仍必须形成当前 Run Evidence 才能支持冲突一方

#### Scenario: 返回双边完整证据
- **WHEN** 当前 Run 存在由不同有效 Evidence 支持的矛盾 Entry
- **THEN** 回答返回冲突双方各自的完整 citation，客户端可分别展示 Source 原文而不按 evidence_id 猜测

#### Scenario: 展示有证据的冲突
- **WHEN** 当前 Run 存在由不同有效 Evidence 支持的矛盾 Entry
- **THEN** 回答并列展示冲突双方、观点和各自引用，且不替用户裁决

#### Scenario: 冲突一方证据不可用
- **WHEN** 疑似冲突的一方无法形成可引用 Evidence
- **THEN** 回答将其标记为待核验或未解决缺口，不返回伪造的双边冲突对象

### Requirement: 可观测性
系统 MUST 对一次问答的上下文决策/改写、回答模式路由、逐轮调查控制器、embedding、重排、工具和最终回答阶段分别记录 provider、model、fallback 状态、error、耗时及轮次/查询归属，并在 Run 响应中汇总降级、预算停止或异常；未配置密钥、任一模型调用失败、工具部分失败或引用校验降级 MUST 明确标记对应阶段和原因，禁止静默降级。

#### Scenario: 正常连续回答记录各阶段来源
- **WHEN** 路由、调查控制器及问答各 AI 阶段均由真实模型完成且引用有效
- **THEN** 每个模型阶段记录实际 provider/model、轮次归属与 `is_fallback=false`，Run 不显示降级

#### Scenario: 正常回答记录各阶段来源
- **WHEN** quick 问答各 AI 阶段均由真实模型完成
- **THEN** 每个模型阶段记录实际 provider/model 与 `is_fallback=false`，Run 不显示降级

#### Scenario: 单阶段降级可识别
- **WHEN** 上下文决策、模式路由、某轮控制器、embedding、重排、工具、引用校验或回答任一阶段降级或失败
- **THEN** 对应阶段记录 fallback 或失败原因，Run 汇总中可识别受影响阶段与轮次

#### Scenario: 正常空搜索不误报
- **WHEN** 某轮搜索成功完成但没有新增相关正式 Entry
- **THEN** 系统记录无进展停止，不把正常空结果标成模型 fallback

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

