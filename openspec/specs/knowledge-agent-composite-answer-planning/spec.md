# knowledge-agent-composite-answer-planning Specification

## Purpose
为 quick 综合回答提供一次受控的复合规划、确定性只读执行、逐项覆盖校验与可恢复快照，同时保持旧协议、范围隔离和人在环上的产品边界。
## Requirements
### Requirement: 复合计划从原始请求形成有界回答义务
系统 MUST 在复合回答能力开启且 `actual_result_mode=answer`、`actual_answer_mode=quick` 时，基于用户原始消息、独立检索问题、Run 固化范围和允许的当前话题用户消息生成版本化回答义务列表；每项义务 MUST 有稳定标识、自然顺序、受限类型与逐项依据策略。系统 MUST NOT 把整条消息压缩成唯一意图或唯一依据，`standalone_query` MUST NOT 替代原始消息中的问题、顺序或限制。

#### Scenario: 一条消息包含通用解释和个人知识
- **WHEN** 用户询问“先解释甲醛是什么，再结合我的知识库说明来源和环保等级”
- **THEN** 计划包含概念解释和个人知识说明两个或多个可追踪回答义务，概念义务可以允许模型知识，个人知识义务要求 Grove，且最终综合仍获得完整原始消息

#### Scenario: 零散统计要求归并为一个数据需求
- **WHEN** 用户同时询问某类知识的总数、按月数量和最近五条
- **THEN** 规划器可以把它们保留为多个回答义务但映射到一份包含多个输出的结构化请求，不要求一句话对应一次工具调用

#### Scenario: 检索改写丢失依据文字
- **WHEN** 上下文决策生成的 `standalone_query` 没有保留原始消息中的“结合我的知识库”
- **THEN** 复合规划和最终综合仍根据原始消息保留 Grove 依据要求，独立问题只用于补全检索表达

#### Scenario: 单一问题保持轻量
- **WHEN** 用户只询问一个无需个人信息或实时材料的通用概念
- **THEN** 计划可以只包含一个 `model_allowed` 回答义务且没有 Grove 输入请求，不为了统一协议强制检索

### Requirement: 模型计划只是候选且由服务端严格规范化
模型候选 MUST 分开表达回答义务、允许的用户消息句柄、Grove 检索请求和受限结构化请求；服务端 MUST 在执行前校验闭合枚举、标识引用、数量、长度、字节、工具与总预算，并以 Run 固化 owner、Workspace 和可选项目注入可信范围。模型或客户端提供的范围、对象标识、未知工具、SQL、写操作、无消费者请求或放宽用户限制的字段 MUST 被拒绝，只有服务端规范化后的计划可以持久化和执行。

#### Scenario: 模型尝试扩大项目范围
- **WHEN** 复合计划候选包含 Workspace id、项目 id、目录 id、Entry id 或要求搜索其他项目
- **THEN** 服务端拒绝计划并记录 composite planning fallback，不执行或泄露扩大范围后的结果

#### Scenario: 显式 knowledge_only 收紧全部义务
- **WHEN** 请求 `basis_mode=knowledge_only` 或原始消息明确要求只使用个人知识库
- **THEN** 服务端把全部可回答义务限制为 Grove-only，拒绝任何 `model_allowed` 或外部一般回答权限，并只允许当前 Run 合法 Grove 输入

#### Scenario: 输入请求关联多个义务
- **WHEN** 一份合法检索或结构化请求声明可满足多个已有回答义务
- **THEN** 服务端保留这组关联并在后续 Evidence、工具事实与覆盖校验中使用，不复制相同结果

#### Scenario: 计划超过预算或引用未知义务
- **WHEN** 候选超过回答义务/输入请求/JSON 上限，或输入请求关联不存在的 requirement id
- **THEN** 服务端将整份候选判为非法、记录原因并进入显式兼容降级，不静默删掉核心请求后继续

### Requirement: quick 复合回答使用固定的一次受控执行图
系统 MUST 在规范化计划固化后执行有界 Grove 检索与 Evidence 读取、结构化请求、服务端工具事实生成和一次最终综合；共享执行图能力关闭时按既有 retrieval → structured 固定顺序逐份执行，能力开启时由服务端把同一计划编译为受限共享只读图并按合法依赖执行。每个原始输入请求和实际图节点 MUST 保留关联回答义务、真实状态、完整性、耗时与有界结果。系统 MUST NOT 允许模型在观察结果后新增请求、改变首次计划、控制图或形成自主循环。

#### Scenario: 通用解释与 Grove 检索组合执行
- **WHEN** 计划包含一个 `model_allowed` 概念义务和一个关联 Grove 检索的 `grove_required` 义务
- **THEN** 系统执行计划内 Grove 读取，并让最终综合在允许边界内同时使用模型一般解释和当前 Run 有效 Evidence；共享图只优化等价输入，不改变逐项依据策略

#### Scenario: 综合回答调用结构化统计
- **WHEN** answer 计划包含经校验的纯结构化 count 和 group_count 请求
- **THEN** 系统通过受控 dispatcher 直接查询 Run 范围内共享集合并把结果作为回答输入，不改为 entries 结果快照或从截断 Entry 列表反推

#### Scenario: 多个请求按固定阶段顺序执行
- **WHEN** 计划包含多个检索请求和结构化请求且共享执行图能力关闭
- **THEN** 系统按规范化计划稳定顺序串行执行并遵守总预算，不进行跨请求 DAG 调度、语义合并或安全并行

#### Scenario: 多个请求共享数据集并按依赖执行
- **WHEN** 计划包含多个检索或结构化请求且服务端能证明其中数据集或输出完全等价
- **THEN** 开启共享图时系统合并等价节点、按确定性拓扑执行并复用结果；无法证明等价或开关关闭时继续按原计划稳定顺序执行

#### Scenario: 已固化计划中的一个工具失败
- **WHEN** 部分输入或图节点失败而其他分支已有合法结果
- **THEN** 系统保留已提交结果、把受影响义务标记为 partial/failed 并继续一次最终综合；已有节点结果后不得回退重跑整条旧 quick 或伪装成全部成功

#### Scenario: 最终回答协议保持一致
- **WHEN** 同一规范化计划分别由现有串行执行器和共享图执行且底层数据没有变化
- **THEN** 两条路径遵守相同 Evidence、工具事实、完整性、逐项覆盖与 answer 协议，客户端无需识别内部图即可展示结果

### Requirement: 结构化工具数值形成服务端事实而非模型数字
系统 MUST 从结构化工具的实际结果生成绑定 requirement id 的不可改写工具事实；事实文本、数值、桶、对象摘要、完整性和边界 MUST 由服务端派生。只有 B1 规则确认 complete 的纯结构化集合可以使用精确全集措辞，semantic query、top-k、预算截断、超时或部分失败 MUST 使用 limited/unknown 边界，模型 MUST NOT 把它们升级为精确结果。

#### Scenario: 精确计数进入综合回答
- **WHEN** 无 semantic query 的授权集合完整完成 count=12
- **THEN** 服务端生成包含精确数值 12 的 tool fact 并作为确定性 answer point 插入对应义务，最终模型不能改写该数字

#### Scenario: 语义统计进入综合回答
- **WHEN** 结构化集合包含 semantic query 并对本次 top-k 候选计数
- **THEN** tool fact 明确只覆盖本次有限匹配，回答不得显示为知识库全部相关内容的精确总数

#### Scenario: 分组完整但列表部分失败
- **WHEN** group_count 为 complete 而同一请求的 Entry 列表为 partial 或 unknown
- **THEN** 系统分别保留各输出完整性，分组事实不因列表失败被改写，整体覆盖如实标记受影响义务

### Requirement: 最终综合按回答义务逐项校验覆盖
最终回答模型 MUST 接收原始消息、规范化回答义务、合法用户陈述、当前 Run Evidence、工具事实和执行缺口，并输出绑定 requirement id 的结构化要点；服务端 MUST 校验 requirement、Evidence 与 result handle 的关联关系，为每项义务派生 `answered`、`partial`、`insufficient` 或 `failed`。只有全部核心义务均有合法回答时整体状态才能为 completed；缺少的义务 MUST 进入 gaps，零散 Citation 或工具命中 MUST NOT 掩盖漏答。

#### Scenario: 最终模型遗漏概念解释
- **WHEN** 计划要求回答“甲醛是什么”及两个 Grove 相关问题，但模型只返回后两个义务的要点
- **THEN** 输出校验在相同证据和工具结果上触发最多一次有界重试；仍缺失时保留合法要点、把概念义务列入 gaps 并将整体状态标为 partial

#### Scenario: Grove-only 要点没有关联依据
- **WHEN** 模型为 `grove_only` 义务返回无 Evidence、无合法 tool fact 的一般文字
- **THEN** 服务端不把该文字计为已回答，将对应义务标记 insufficient 或 partial，且实际依据不声明使用了 Grove

#### Scenario: 一个 Evidence 绑定到无关义务
- **WHEN** 模型把某个句柄用于未关联该 Evidence 检索请求的 requirement id
- **THEN** 服务端拒绝该绑定并按剩余合法要点重新计算逐项覆盖、Citation 和整体状态

#### Scenario: 外部材料义务当前不可完成
- **WHEN** 某项义务依赖当前政策、价格或其他实时材料且没有真实外部工具结果
- **THEN** 系统最多保留允许的一般框架并将外部核验列为 partial/insufficient 缺口，不声称已联网或已核验

### Requirement: 复合回答计划、执行和覆盖可恢复且可观测
系统 MUST 在工具执行前持久化规范化计划；启用共享图时还 MUST 在节点执行前持久化与计划绑定的规范化图和冻结预算，并在每个节点终态后保存有界检查点，未启用时继续在每个输入请求完成后保存既有执行检查点。终态 MUST 原子提交 answer、实际依据、逐项覆盖、Run 状态与活动槽释放；同一 `client_message_id`、Worker 恢复和历史读取 MUST 复用首次计划及所有已提交请求/节点结果。规划、图编译、检索、Evidence、结构化工具、调度和最终综合 MUST 按实际发生情况记录 purpose、provider、model、fallback、error、duration、usage、复用状态、工具状态和完整性。

#### Scenario: Worker 在一个输入请求后退出
- **WHEN** 共享执行图能力关闭，Run 已固化计划并提交第一份检索结果后租约超时
- **THEN** 恢复复用同一计划和已完成请求，只重放未完成的只读请求，不再次调用复合规划模型

#### Scenario: Worker 在一个共享节点后退出
- **WHEN** Run 已固化计划与共享图并提交第一项节点结果后租约超时
- **THEN** 恢复复用同一计划、图、冻结预算与所有终态节点，只重放未提交节点，不再次调用复合规划模型或已完成工具

#### Scenario: 图编译失败后旧执行成功
- **WHEN** 图尚未执行即编译、校验或首次持久化失败，而既有复合串行执行路径成功
- **THEN** Run 可以返回旧协议回答，但 fallback 摘要明确记录共享图失败，不伪装成共享执行正常完成

#### Scenario: 规划失败后旧 quick 成功
- **WHEN** 复合规划模型未配置、超时、失败或返回非法结构，而旧 basis/quick 兼容路径成功
- **THEN** Run 可以返回旧协议回答，但 fallback 摘要明确记录 composite planning 失败，不伪装成复合回答正常完成

#### Scenario: 处理期间取消
- **WHEN** 用户在复合规划、图节点、串行工具或最终综合期间请求取消
- **THEN** Worker 在下一安全边界停止、停止启动新节点并丢弃未提交的迟到结果，Run 进入 cancelled，不提交正常回答或推进事实工作集

#### Scenario: 历史恢复读取同一覆盖快照
- **WHEN** 用户重新打开已完成复合回答的 Conversation
- **THEN** API 返回生成时的计划摘要、逐项覆盖、answer、points、Citation 和实际依据，不返回内部图，不重新规划、查询或按当前范围改写历史

### Requirement: 复合回答保持协议兼容且没有写入副作用
复合回答 MUST 继续使用现有 `actual_result_mode=answer`、`answer`、`points`、`citations`、`coverage`、`gaps` 与 basis 协议，并只追加旧客户端可忽略的可选字段；旧 Run 缺少复合字段时 MUST 按原记录读取且不得反向猜测。规划、查询、统计、综合、恢复和取消 MUST NOT 创建或修改 Entry、Source、Candidate、Draft、目录或事实工作集。

#### Scenario: 旧客户端读取复合回答
- **WHEN** 不识别 requirement id、计划摘要或逐项覆盖字段的客户端读取新回答
- **THEN** 它仍可通过服务端拼接的 answer、原有 points、Citation、status 和 gaps 展示诚实结果

#### Scenario: 新客户端读取旧 Run
- **WHEN** 历史 Run 没有复合计划、执行或覆盖 JSON
- **THEN** API 返回复合字段为空并保留原 answer/entries/basis 行为，不生成伪造的回答义务或实际依据

#### Scenario: 查询文字包含修改要求
- **WHEN** 复合问题中夹带“顺便把这些知识改掉”等写入意图但未进入独立操作协议
- **THEN** 本执行图只回答允许的只读部分或把写入部分列为不支持，不调用 `prepare_operation` 或修改任何正式对象

#### Scenario: 完成复合回答
- **WHEN** 复合 Run 正常完成并引用多个 Entry 或结构化事实
- **THEN** 只持久化 Conversation、Message、Run、Evidence、工具审计和回答快照，事实工作集不因搜索命中或统计结果自动推进

### Requirement: 首次 coverage 可以触发一次受控缺口补查
系统 MUST 保持首次 `CompositeAnswerPlan` 不变，并在首次合法综合与逐项 coverage 持久化后，最多针对可修复的 `partial/insufficient` 义务进行一次有界补查。最终综合 MUST 只使用首次和补查阶段已提交的合法 Evidence、tool fact、允许的用户陈述与依据边界，并重算逐项 coverage、answer basis、Citation、gaps 和 Run 终态；补查失败 MUST 保留首次合法回答。

#### Scenario: 补查改善一项义务
- **WHEN** 首次 coverage 的某项 Grove 义务为 `insufficient`，补查产生了与该义务合法关联的新 Evidence
- **THEN** 最终综合可将该义务改为 `answered/partial`，其他已回答义务沿用原合法依据且首次计划摘要不变

#### Scenario: 补查后仍有缺口
- **WHEN** 补查结束后某项义务仍无合法依据或只有有限结果
- **THEN** 最终 coverage 继续显示 `insufficient/partial` 和剩余 gap，不因已执行过补查而标为 completed

#### Scenario: 补查再综合失败
- **WHEN** 首次回答已通过服务端校验，但补查后的最终回答模型不可用或输出非法
- **THEN** 系统返回首次合法 answer/points/Citation/coverage/basis 并记录补查综合 fallback，不以空结果覆盖它
