## ADDED Requirements

### Requirement: Run 持久化请求策略与实际回答依据
系统 MUST 为 answer Run 固化 `request_basis_mode`，并在规划后持久化内部 `planned_basis_strategy`；终态回答 MUST 保存服务端校验后的版本化实际依据。客户端查询 Run 或恢复消息历史时 MUST 获得生成时的请求依据模式和实际依据摘要，旧 Run 缺少这些字段时 MUST 保持可读且不得反向猜测未记录的依据。

#### Scenario: 新问题固化依据覆盖
- **WHEN** 空闲 Conversation 接受一条 `basis_mode=knowledge_only` 的新问题
- **THEN** waiting Run 固化该请求模式，网络重试返回同一 Run 和同一模式

#### Scenario: 自动规划结果持久化
- **WHEN** basis planner 为自动请求选择 `hybrid`
- **THEN** Run 保存规划策略，并在崩溃恢复时复用该结果而不重新漂移到另一策略

#### Scenario: 历史 Run 缺少 basis 字段
- **WHEN** 客户端恢复本 change 上线前生成的回答 Run
- **THEN** 系统返回可空的 basis 字段、原回答与 Citation，不因缺少 basis 数据而迁移失败或伪造完整依据

### Requirement: 依据规划与实际执行可观测
系统 MUST 为实际发生的依据规划保存 purpose、prompt 版本、provider、model、fallback、error、duration 和可用 usage，并把依据规划失败汇总到 Run 降级摘要；确定性遵守显式 `knowledge_only` 或确定性跳过 Grove 工具 MUST NOT 伪造成一次模型或工具调用。

#### Scenario: 自动依据规划成功
- **WHEN** 配置模型成功返回合法依据策略
- **THEN** 模型调用记录包含真实 provider/model、`is_fallback=false`、prompt 版本与耗时

#### Scenario: 自动依据规划失败后回答成功
- **WHEN** basis planner 失败并安全回退 `knowledge_only`，后续 Grove-only 回答成功
- **THEN** Run 仍汇总依据规划 fallback，客户端能识别本次回答未按正常自动策略完成

#### Scenario: 显式 knowledge_only 跳过规划器
- **WHEN** 用户结构化选择 `knowledge_only`
- **THEN** 应用直接固化限制，不创建虚假的 basis planner 模型调用记录

#### Scenario: model_first 正常跳过 Grove
- **WHEN** 自动规划合法选择 `model_first` 且用户未强制 investigate
- **THEN** 不调用 Grove 搜索工具、不记录伪工具错误或 fallback，并持久化实际未使用 Grove

## MODIFIED Requirements

### Requirement: 终态提交保持一致
系统 MUST 在同一事务中提交助手消息结果、Run 终态、实际结果形态、综合回答或结构化 Entry 结果、服务端校验后的实际回答依据、可选 Investigation 终态与调查摘要、活动槽释放以及可选输出工作集版本；失败、取消、澄清或重复执行 MUST NOT 留下被当作正常回答、实际依据、结构化结果或活动上下文的半成品状态。输出工作集只可包含综合回答最终有效引用实际使用的 Entry，用户陈述、模型通用知识与结构化搜索命中不得作为工作集 Entry。

#### Scenario: 回答与工作集提交成功
- **WHEN** 调查停止、最终回答、引用与实际依据通过校验且满足工作集推进条件
- **THEN** 系统原子写入助手消息、Run/Investigation 终态与摘要、实际依据、新工作集版本并释放活动槽

#### Scenario: 无引用回答提交成功
- **WHEN** quick 模型优先回答在允许范围内完整生成且没有 Grove Citation
- **THEN** 系统原子写入助手消息、`completed` Run 与模型通用知识依据并释放活动槽，不创建包含 Entry 的输出工作集

#### Scenario: 混合回答提交成功
- **WHEN** quick 回答、最终引用与用户陈述句柄通过校验
- **THEN** 系统原子写入回答、实际多类依据、`completed` 或 `partial` 终态和只含最终引用 Entry 的可选工作集

#### Scenario: 结构化 Entry 结果提交成功
- **WHEN** `actual_result_mode=entries` 的搜索和结果装配完成
- **THEN** 系统原子写入助手兼容摘要、Run 终态、稳定结果快照与完整性信息并释放活动槽，不创建回答依据或输出工作集版本

#### Scenario: 澄清回复提交成功
- **WHEN** 上下文决策要求澄清
- **THEN** 系统原子写入澄清助手消息与 Run 终态，但不创建 Investigation、结构化 Entry 结果、实际回答依据或输出工作集版本

#### Scenario: 发现但未引用的 Entry
- **WHEN** 调查搜索到 Entry 但最终回答没有有效引用使用它
- **THEN** 该 Entry 保留在调查审计中但不计入实际 Grove 依据、不加入输出工作集

#### Scenario: 最终提交失败
- **WHEN** 数据库在提交助手结果、实际依据、结构化 Entry 结果、调查终态或新工作集时失败
- **THEN** 系统不暴露部分完成答案、半份依据或对象快照、不切换活动工作集，且 Run 可按恢复规则重试或失败

### Requirement: 知识问答使用 quick 或有界调查执行图
系统 MUST 在上下文决策与结果形态确定后解析用户依据限制并选择回答依据，再按实际回答模式执行 model-only quick、现有 quick Grove 固定单轮图或由应用控制且服务端预算限制的调查循环；当前 Run 的 Grove 事实 MUST 只来自重新读取的正式 Entry 与 Evidence，当前话题用户陈述与模型通用知识只能在依据策略允许时进入回答。模型 MUST NOT 自行创建无限工具循环、指定可信范围或把非 Grove 内容包装成 Citation。

#### Scenario: model_first quick 正常完成
- **WHEN** 自动依据规划选择 `model_first` 且没有显式 investigate 覆盖
- **THEN** 系统跳过 Grove 搜索、Entry/Evidence 读取与调查路由，以实际 quick 模式生成可无 Citation 的开放回答

#### Scenario: quick 继续追问正常完成
- **WHEN** Worker 领取一个需要 Grove、有活动工作集的 quick `continue` Run 且各阶段成功
- **THEN** 系统合并复验后的工作集种子与新召回，生成本 Run Evidence、依据感知回答和可选新工作集版本

#### Scenario: investigate 正常完成
- **WHEN** actual mode 为 investigate 且调查在预算内完成若干轮
- **THEN** 应用逐轮执行固定只读工具链，并用最终账本、允许的用户陈述和依据策略生成一次回答

#### Scenario: 新话题正常完成
- **WHEN** Run 决策为 `new_topic`
- **THEN** 系统不使用旧工作集种子或旧话题用户陈述，按当前独立问题执行所选依据与回答模式；只有有效 Citation 对应 Entry 可以进入工作集

#### Scenario: 历史助手消息不作为事实
- **WHEN** 同一 Conversation 提交 quick 或 investigate 追问
- **THEN** 有限历史助手消息只参与意图、路由与查询理解，不成为用户陈述、Grove Evidence 或独立事实依据

#### Scenario: 工具达到预算上限
- **WHEN** quick 工具或调查的轮次、查询、结果、Entry、Evidence 已达到服务端上限
- **THEN** 系统停止扩张，并按用户依据限制基于已有合法依据继续，或明确标记部分结果、知识不足与停止原因
