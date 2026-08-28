## MODIFIED Requirements

### Requirement: 持久化异步 Run
系统 MUST 为每条被接受的用户问题创建持久化只读 Agent Run，并立即返回 Run 标识；Run MUST 固化用户消息、助手消息、Workspace/项目范围、请求上下文模式、输入工作集版本和创建时间，并在可用时持久化实际上下文决策与输出工作集版本；客户端 MUST 能通过查询恢复执行状态和当前步骤。

#### Scenario: 问题进入等待状态
- **WHEN** 空闲对话接受一条新用户问题
- **THEN** 系统创建状态为 `waiting` 的 Run，固化请求模式与输入版本并立即返回

#### Scenario: 客户端恢复执行状态
- **WHEN** 客户端在提交后断线并重新查询 Run
- **THEN** 系统返回持久化的状态、当前步骤、范围快照、上下文决策、工作集版本、降级摘要和终态结果

#### Scenario: 运行中步骤可见
- **WHEN** Worker 已从上下文决策推进到搜索、证据读取或回答阶段
- **THEN** 其他请求通过轮询能读取最近提交的 `current_step`，而非始终停留在领取步骤

### Requirement: Run 可取消
系统 MUST 允许对话所有者取消 `waiting` 或 `processing` Run；Worker MUST 通过能读取其他事务最新提交状态的短会话在步骤边界检查取消请求，取消后的模型结果 MUST NOT 写成正常回答或推进工作集。

#### Scenario: 取消等待中的 Run
- **WHEN** 用户取消尚未领取的 `waiting` Run
- **THEN** 系统将其标记为 `cancelled`、释放活动槽且 Worker 不再执行

#### Scenario: 取消处理中的 Run
- **WHEN** 用户取消正在模型调用中的 Run
- **THEN** 系统记录取消请求，并在下一个可中断点从最新数据库状态识别取消、丢弃未提交结果且不更新工作集

#### Scenario: MySQL 长事务期间取消
- **WHEN** Worker 在 MySQL 执行长事务且另一请求提交取消
- **THEN** 后续步骤边界使用独立短会话看到最新取消状态并终止 Run

#### Scenario: 取消其他用户的 Run
- **WHEN** 用户请求取消无权访问的 Run
- **THEN** 系统返回 404 且不改变该 Run

### Requirement: 终态提交保持一致
系统 MUST 在同一事务中提交助手消息结果、Run 终态、活动槽释放以及可选输出工作集版本；失败、取消、澄清或重复执行 MUST NOT 留下被当作正常事实回答或活动上下文的半成品状态。

#### Scenario: 回答与工作集提交成功
- **WHEN** 回答和引用通过最终校验且满足工作集推进条件
- **THEN** 系统原子写入助手消息、Run 结果、`completed` 或 `partial` 终态、新工作集版本并释放活动槽

#### Scenario: 澄清回复提交成功
- **WHEN** 上下文决策要求澄清
- **THEN** 系统原子写入澄清助手消息与 Run 终态，但不创建输出工作集版本

#### Scenario: 最终提交失败
- **WHEN** 数据库在提交助手回答或新工作集时失败
- **THEN** 系统不暴露部分完成答案、不切换活动工作集，且 Run 可按恢复规则重试或失败

### Requirement: 分阶段 AI 可观测性
系统 MUST 为上下文决策/改写、embedding、重排、回答及每次工具调用保存阶段、provider、model、fallback 状态、错误和耗时，并在 Run 上汇总用户可识别的降级或异常状态；正常空结果 MUST NOT 误报为 fallback，工具部分失败或错误 MUST NOT 被记录为完全正常。

#### Scenario: 全阶段正常
- **WHEN** 上下文决策、embedding、重排和回答均由配置的真实模型成功完成且工具正常
- **THEN** 各模型阶段记录实际 provider/model 与 `is_fallback=false` 且 Run 无降级摘要

#### Scenario: embedding 降级但回答成功
- **WHEN** embedding 失败后使用确定性召回且回答模型成功
- **THEN** embedding 阶段记录降级原因，其他阶段记录实际模型，Run 汇总为部分降级

#### Scenario: 上下文决策降级
- **WHEN** 自动上下文决策模型不可用并安全回退为新话题
- **THEN** 决策阶段记录 provider/model/fallback/error，Run 汇总可识别该阶段

#### Scenario: 工具正常空结果
- **WHEN** 搜索在当前范围正常完成但没有相关 Entry
- **THEN** 工具记录 `empty`，回答标记知识不足且 Run 不把该空结果误报为 fallback

#### Scenario: 工具错误或部分失败
- **WHEN** 工具调用发生 error、denied、unavailable 或 partial
- **THEN** Run 汇总包含受影响工具和原因且不得标记为完全正常

#### Scenario: 回答模型不可用
- **WHEN** 检索已有结果但回答模型未配置或调用失败
- **THEN** 系统明确记录回答阶段失败并将 Run 标为 `partial` 或 `failed`，不得伪装为正常 AI 回答

## REMOVED Requirements

### Requirement: 首次问答使用固定有限执行图
**Reason**: 知识 Agent 已从独立首次问答演进为带上下文决策和显式工作集的连续问答，原名称与“历史消息完全不参与”的场景不再成立。

**Migration**: 由新增的“连续问答使用固定有限执行图”需求替代；新话题仍沿用原搜索、Entry、Evidence、回答和引用校验步骤。

## ADDED Requirements

### Requirement: 连续问答使用固定有限执行图
系统 MUST 按“上下文决策、澄清或工作集种子复验与新检索、读取 Entry、读取真实来源证据、组织回答、校验引用、可选更新工作集”的固定分支执行连续问答；每个模型与工具步骤 MUST 有服务端上限，模型 MUST NOT 自行创建无限工具循环。

#### Scenario: 继续追问正常完成
- **WHEN** Worker 领取一个有活动工作集的 `continue` Run 且各阶段成功
- **THEN** 系统合并复验后的工作集种子与新召回，生成本 Run Evidence、回答和新工作集版本

#### Scenario: 新话题正常完成
- **WHEN** Run 决策为 `new_topic`
- **THEN** 系统不使用旧工作集种子，按当前独立查询完成问答；有有效引用时建立含 Entry 的新版本，知识不足时可建立只含主题标签的空版本

#### Scenario: 历史消息不作为事实
- **WHEN** 同一对话提交追问
- **THEN** 有限历史只参与意图与查询改写，回答事实仍只来自本轮重新读取的正式 Entry 与 Evidence

#### Scenario: 工具达到预算上限
- **WHEN** 某工具已达到本 Run 的调用、结果或工作集上限
- **THEN** 系统停止扩张并基于已有有效证据继续或明确标记知识不足
