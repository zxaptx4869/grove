## MODIFIED Requirements

### Requirement: 知识问答使用 quick 或有界调查执行图
系统 MUST 在上下文决策与结果形态确定后先解析回答模式；启用复合回答的 quick Run MUST 基于原始消息生成并校验多回答义务，再按固定一次执行图使用允许的用户陈述、Grove 检索/Evidence、受限结构化工具和模型通用知识。investigate 与未启用复合能力的 quick Run继续使用兼容依据规划和既有固定图。当前 Run 的 Grove 事实 MUST 只来自重新读取的正式 Entry 与 Evidence，结构化事实 MUST 来自实际工具结果，模型 MUST NOT 自行创建无限工具循环、指定可信范围或把非 Grove 内容包装成 Citation。

#### Scenario: 单一模型知识 quick 正常完成
- **WHEN** 复合计划只有一个 `model_allowed` 义务且没有显式 investigate 覆盖
- **THEN** 系统跳过 Grove 工具，以实际 quick 模式生成可无 Citation 的开放回答并保存逐项覆盖；兼容路径仍可使用 `model_first`

#### Scenario: 复合 quick 正常完成
- **WHEN** quick Run 同时包含通用解释、Grove 知识与结构化统计义务
- **THEN** 系统按固化计划执行对应只读输入、生成服务端工具事实并一次综合为 answer，不强制选择唯一依据或改成 entries

#### Scenario: quick 继续追问正常完成
- **WHEN** Worker 领取一个有活动工作集的 quick `continue` Run 且各阶段成功
- **THEN** 系统只把复验后的工作集种子作为计划内 Grove 检索输入，与新召回统一处理；历史回答不成为事实，复合回答不得因搜索命中自动推进工作集

#### Scenario: investigate 正常完成
- **WHEN** actual mode 为 investigate 且调查在预算内完成若干轮
- **THEN** 应用继续逐轮执行既有固定只读工具链，并用最终账本、允许的用户陈述和兼容依据策略生成一次回答，本 change 不插入复合执行图

#### Scenario: 新话题正常完成
- **WHEN** Run 决策为 `new_topic`
- **THEN** 系统不使用旧工作集种子或旧话题用户陈述，按当前原始问题执行所选 quick/investigate 图；只有既有规则允许时才形成输出工作集

#### Scenario: 历史消息不作为事实
- **WHEN** 同一 Conversation 提交 quick 或 investigate 追问
- **THEN** 有限历史助手消息只参与意图、路由与查询理解，不成为回答义务、用户陈述、Grove Evidence 或独立事实依据

#### Scenario: 工具达到预算上限
- **WHEN** quick 复合输入或调查的请求、查询、结果、Entry、Evidence、桶或字节达到服务端上限
- **THEN** 系统停止扩张，并按用户依据限制基于已有合法依据继续，或明确标记受影响义务、部分结果、知识不足与停止原因

### Requirement: Run 持久化请求策略与实际回答依据
系统 MUST 为 answer Run 固化 `request_basis_mode`；复合 quick Run MUST 在工具执行前持久化服务端规范化的版本化回答计划，并在执行后保存有界输入结果与逐项覆盖快照。兼容 quick/investigate 继续保存内部 `planned_basis_strategy` 与既有计划。任何计划快照 MUST 只保存恢复所需的义务、受限请求、策略和候选用户消息 ID，不复制消息正文或原始模型输出；崩溃恢复 MUST 复用首次计划和已完成输入，只可因对象或消息失效而收紧。终态回答 MUST 保存服务端校验后的实际依据，旧 Run 缺少新增字段时 MUST 保持可读且不得反向猜测。

#### Scenario: 新问题固化依据覆盖
- **WHEN** 空闲 Conversation 接受一条 `basis_mode=knowledge_only` 的新问题
- **THEN** waiting Run 固化该请求模式，网络重试返回同一 Run 和同一模式

#### Scenario: 自动复合计划持久化
- **WHEN** composite planner 为 quick 请求生成合法多义务计划
- **THEN** Run 在任何相关工具执行前保存服务端规范化计划，并在崩溃恢复时复用它而不重新规划、扩大消息集合或改变义务

#### Scenario: 兼容依据规划结果持久化
- **WHEN** investigate 或降级后的 basis planner 选择 `hybrid`
- **THEN** Run 继续保存兼容策略和候选用户消息 ID 子集，并按原恢复规则复用

#### Scenario: 已完成输入请求被恢复
- **WHEN** 复合 Run 已提交一份检索或结构化请求结果后 Worker 中断
- **THEN** 恢复使用同 Run 稳定指纹复用该有界结果，只重放尚未完成的只读请求

#### Scenario: 历史 Run 缺少复合字段
- **WHEN** 客户端恢复本 change 上线前生成的回答 Run
- **THEN** 系统返回可空复合计划/执行/覆盖字段、原回答与 Citation，不因缺少新数据而迁移失败或伪造完整依据

### Requirement: 依据规划与实际执行可观测
系统 MUST 为实际发生的复合规划或兼容依据规划保存独立 purpose、prompt 版本、provider、model、fallback、error、duration 和可用 usage；复合输入请求、结构化工具、Evidence 与综合必须记录真实工具状态、完整性和耗时，并把失败汇总到 Run 降级摘要。确定性遵守显式 `knowledge_only`、特性开关关闭或按计划跳过工具 MUST NOT 伪造成模型/工具调用。

#### Scenario: 自动复合规划成功
- **WHEN** 配置模型成功返回合法复合计划且服务端规范化完成
- **THEN** 模型调用记录包含真实 provider/model、`is_fallback=false`、复合 prompt 版本与耗时，Run 摘要能区分它与旧 basis route

#### Scenario: 复合规划失败后兼容回答成功
- **WHEN** composite planner 失败并显式降级到旧 basis/quick，后续回答成功
- **THEN** Run 仍汇总 composite planning fallback，客户端能识别本次没有按复合路径正常完成

#### Scenario: 显式 knowledge_only 仍执行复合规划
- **WHEN** quick 请求显式 `knowledge_only` 且复合能力开启
- **THEN** 规划器可以拆解回答义务，但服务端确定性把全部策略收紧为 Grove-only；不得把该收紧伪造成模型自主决定

#### Scenario: 计划不需要 Grove
- **WHEN** 合法复合计划只有模型允许义务且没有 Grove 输入请求
- **THEN** 系统不调用 Grove 工具、不记录伪工具错误或 fallback，并持久化实际未使用 Grove

#### Scenario: 结构化工具部分失败
- **WHEN** 一份结构化请求部分失败但其他输入有效
- **THEN** 对应工具调用和义务覆盖标记真实 partial/unknown，成功响应不得掩盖受影响阶段
