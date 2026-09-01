## MODIFIED Requirements

### Requirement: 持久化异步 Run
系统 MUST 为每条被接受的用户问题创建持久化只读 Agent Run，并立即返回 Run 标识；Run MUST 固化用户消息、助手消息、Workspace/项目范围、请求上下文模式、请求结果形态、请求回答模式、输入工作集版本和创建时间，并在可用时持久化实际上下文决策、实际结果形态、实际回答模式、输出工作集版本、结构化 Entry 结果与调查摘要；客户端 MUST 能通过查询恢复执行状态、当前步骤和当前调查轮次。

#### Scenario: 问题进入等待状态
- **WHEN** 空闲对话接受一条新用户问题
- **THEN** 系统创建状态为 `waiting` 的 Run，固化上下文模式、结果形态、回答模式与输入版本并立即返回

#### Scenario: 客户端恢复执行状态
- **WHEN** 客户端在提交后断线并重新查询 Run
- **THEN** 系统返回持久化的状态、当前步骤/轮次、范围快照、上下文决策、请求/实际结果形态、请求/实际回答模式、工作集版本、综合回答或结构化 Entry 结果、调查摘要和降级摘要

#### Scenario: 运行中步骤可见
- **WHEN** Worker 已推进到结果形态路由、调查路由、结构化 Entry 搜索、轮次计划、证据读取或综合阶段
- **THEN** 其他请求通过轮询能读取最近提交的 `current_step` 与当前轮次，而非始终停留在领取步骤

### Requirement: 终态提交保持一致
系统 MUST 在同一事务中提交助手消息结果、Run 终态、实际结果形态、综合回答或结构化 Entry 结果、可选 Investigation 终态与调查摘要、活动槽释放以及可选输出工作集版本；失败、取消、澄清或重复执行 MUST NOT 留下被当作正常事实回答、结构化结果或活动上下文的半成品状态。输出工作集只可包含综合回答最终有效引用实际使用的 Entry，结构化搜索命中不得自动进入工作集。

#### Scenario: 回答与工作集提交成功
- **WHEN** 调查停止、最终回答和引用通过校验且满足工作集推进条件
- **THEN** 系统原子写入助手消息、Run/Investigation 终态与摘要、新工作集版本并释放活动槽

#### Scenario: 回答提交成功
- **WHEN** quick 回答和引用通过最终校验
- **THEN** 系统原子写入助手消息、Run 结果与 `completed` 或 `partial` 终态、可选工作集版本并释放活动槽

#### Scenario: 结构化 Entry 结果提交成功
- **WHEN** `actual_result_mode=entries` 的搜索和结果装配完成
- **THEN** 系统原子写入助手兼容摘要、Run 终态、稳定结果快照与完整性信息并释放活动槽，不创建输出工作集版本

#### Scenario: 澄清回复提交成功
- **WHEN** 上下文决策要求澄清
- **THEN** 系统原子写入澄清助手消息与 Run 终态，但不创建 Investigation、结构化 Entry 结果或输出工作集版本

#### Scenario: 发现但未引用的 Entry
- **WHEN** 调查搜索到 Entry 但最终回答没有有效引用使用它
- **THEN** 该 Entry 保留在调查审计中但不加入输出工作集

#### Scenario: 最终提交失败
- **WHEN** 数据库在提交助手结果、结构化 Entry 结果、调查终态或新工作集时失败
- **THEN** 系统不暴露部分完成答案或半份对象快照、不切换活动工作集，且 Run 可按恢复规则重试或失败

### Requirement: 分阶段 AI 可观测性
系统 MUST 为上下文决策/改写、结果形态路由、回答模式路由、每轮调查控制器、embedding、重排、最终回答及每次工具调用保存阶段、provider、model、fallback 状态、错误、耗时与可选轮次/查询归属，并在 Run 上汇总用户可识别的降级、预算停止或异常状态；正常空结果 MUST NOT 误报为 fallback，工具部分失败或错误 MUST NOT 被记录为完全正常。

#### Scenario: 全阶段正常
- **WHEN** 结果路由、回答路由、各轮控制器、embedding、重排和回答均由配置模型成功完成且工具正常
- **THEN** 各实际执行阶段记录 provider/model、轮次归属与 `is_fallback=false`，Run 无降级摘要

#### Scenario: 结果形态路由失败
- **WHEN** auto 结果路由失败并按规则回退综合回答
- **THEN** 结果路由阶段记录 fallback/error，Run 返回实际结果形态 answer 且不得把整次执行标为完全正常

#### Scenario: 路由失败后 quick 成功
- **WHEN** actual result 为 answer 且 auto 回答路由失败并按规则回退 quick，后续问答成功
- **THEN** 回答路由阶段记录 fallback/error，Run 返回实际回答模式 quick 且不得把整次执行标为完全正常

#### Scenario: embedding 降级但回答成功
- **WHEN** 某轮 embedding 失败后使用确定性召回且后续阶段成功
- **THEN** 对应轮次的 embedding 记录降级原因，其他阶段记录实际模型，Run 汇总为部分降级

#### Scenario: 上下文决策降级
- **WHEN** 自动上下文决策模型不可用并安全回退为新话题
- **THEN** 决策阶段记录 provider/model/fallback/error，Run 汇总可识别该阶段

#### Scenario: 控制器非法输出
- **WHEN** 某轮控制器返回非法 schema 或越权字段
- **THEN** 该轮模型调用记录错误/降级与处理结果，Run 汇总可识别受影响轮次

#### Scenario: 工具正常空结果
- **WHEN** 综合回答或结构化 Entry 查找在当前范围正常完成但没有新 Entry
- **THEN** 工具记录 `empty`，Run 按对应结果语义完成且不把空结果误报为模型 fallback

#### Scenario: 工具错误或部分失败
- **WHEN** 工具调用发生 error、denied、unavailable 或 partial
- **THEN** Run 汇总包含受影响轮次、查询、工具和原因且不得标记为完全正常

#### Scenario: 回答模型不可用
- **WHEN** actual result 为 answer、调查已有结果但最终回答模型未配置或调用失败
- **THEN** 系统明确记录回答阶段失败并将 Run 标为 `partial` 或 `failed`，不得伪装为正常 AI 回答

## ADDED Requirements

### Requirement: 结构化 Entry 查找使用独立有界执行图
系统 MUST 在上下文决策后先解析结果形态；`actual_result_mode=entries` MUST 执行固定的“结果路由完成 → 受控搜索 → 去重与范围复验 → 快照装配 → 原子提交”只读图，跳过回答模式路由、调查循环、Evidence 读取与最终回答模型。该执行图 MUST 复用 Run 领取、租约恢复、取消、单会话活动槽和预算约束。

#### Scenario: Entry 查找正常完成
- **WHEN** Worker 领取一个实际结果形态为 entries 的 answer Run
- **THEN** 系统按服务端上限搜索正式 Entry、保存结构化结果与完整性，不调用回答模型或生成 Citation

#### Scenario: Entry 查找崩溃恢复
- **WHEN** Worker 在搜索或结果装配后退出且 Run 超过租约
- **THEN** 系统在重试上限内重放同一有界图，并以同一 Run 原子覆盖未提交半成品，不创建第二个结果集

#### Scenario: 取消 Entry 查找
- **WHEN** 用户取消 waiting 或 processing 的 Entry 查找 Run
- **THEN** Worker 在下一安全边界停止，Run 进入 cancelled，不提交正常结果或改变工作集

#### Scenario: 显式结果形态跳过路由
- **WHEN** `request_result_mode` 为 answer 或 entries
- **THEN** Worker 直接固化对应 actual 结果形态，且可观测记录中不伪造一次未发生的结果路由模型调用
