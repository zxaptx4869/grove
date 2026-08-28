# knowledge-agent-run Specification

## Purpose
一次只读问答的持久化 Run：固定有限执行图、状态机与单会话串行，支持取消、崩溃恢复与分阶段 AI 可观测性。
## Requirements
### Requirement: 持久化异步 Run
系统 MUST 为每条被接受的用户问题创建持久化只读 Agent Run，并立即返回 Run 标识；Run MUST 固化用户消息、助手消息、Workspace/项目范围、请求上下文模式、请求回答模式、输入工作集版本和创建时间，并在可用时持久化实际上下文决策、实际回答模式、输出工作集版本与调查摘要；客户端 MUST 能通过查询恢复执行状态、当前步骤和当前调查轮次。

#### Scenario: 问题进入等待状态
- **WHEN** 空闲对话接受一条新用户问题
- **THEN** 系统创建状态为 `waiting` 的 Run，固化上下文模式、回答模式与输入版本并立即返回

#### Scenario: 客户端恢复执行状态
- **WHEN** 客户端在提交后断线并重新查询 Run
- **THEN** 系统返回持久化的状态、当前步骤/轮次、范围快照、上下文决策、请求/实际回答模式、工作集版本、调查摘要、降级摘要和终态结果

#### Scenario: 运行中步骤可见
- **WHEN** Worker 已推进到调查路由、轮次计划、搜索、证据读取或综合阶段
- **THEN** 其他请求通过轮询能读取最近提交的 `current_step` 与当前轮次，而非始终停留在领取步骤

### Requirement: Run 状态与单会话串行
系统 MUST 仅允许 Run 在 `waiting`、`processing`、`completed`、`partial`、`failed`、`cancelled` 状态间按合法路径转换；同一对话 MUST 最多存在一个 `waiting` 或 `processing` Run。

#### Scenario: 活动 Run 时提交新问题
- **WHEN** 对话已有 `waiting` 或 `processing` Run 且用户提交新的 `client_message_id`
- **THEN** 系统返回冲突响应且不创建第二个活动 Run

#### Scenario: 终态后提交新问题
- **WHEN** 对话最近 Run 已进入任一终态且用户提交新问题
- **THEN** 系统允许创建新的 `waiting` Run

#### Scenario: 非法状态转换
- **WHEN** 执行器尝试将终态 Run 重新改为 `processing`
- **THEN** 系统拒绝转换且保留原终态

### Requirement: Run 领取与崩溃恢复
Worker MUST 通过数据库原子操作领取待执行 Run，并记录领取时间与重试次数；超过租约阈值的 `processing` Run MUST 在重试上限内恢复，quick Run MUST 安全重放单轮执行图，investigate Run MUST 复用已完成轮次与账本并从下一未完成步骤继续；超过上限 MUST 进入可解释的失败终态。

#### Scenario: 两个 Worker 竞争领取
- **WHEN** 两个 Worker 同时尝试领取同一个 `waiting` Run
- **THEN** 只有一个 Worker 获得执行权且不会提交两份助手回答或重复调查轮次

#### Scenario: Worker 重启后恢复
- **WHEN** Worker 在 quick 只读执行中退出且 Run 超过处理租约
- **THEN** 系统在重试上限内将 Run 重新入队并安全重放单轮执行图

#### Scenario: investigation Worker 重启后恢复
- **WHEN** Worker 在调查中退出且已有完成轮次
- **THEN** 系统在重试上限内复用已提交轮次和账本并从下一未完成步骤继续

#### Scenario: 超过恢复上限
- **WHEN** 同一 Run 连续超过允许的恢复次数
- **THEN** 系统将 Run 及活动 Investigation 标记为 `failed`、释放会话活动槽并记录恢复失败原因

### Requirement: Run 可取消
系统 MUST 允许对话所有者取消 `waiting` 或 `processing` Run；Worker MUST 通过能读取其他事务最新提交状态的短会话，在上下文决策、回答模式路由、每轮控制器、查询工具批次、证据读取和最终综合边界检查取消请求，取消后的模型或工具结果 MUST NOT 写成正常回答或推进工作集。

#### Scenario: 取消等待中的 Run
- **WHEN** 用户取消尚未领取的 `waiting` Run
- **THEN** 系统将其标记为 `cancelled`、释放活动槽且 Worker 不再执行

#### Scenario: 取消处理中的 Run
- **WHEN** 用户取消正在模型调用中的 quick Run
- **THEN** 系统记录取消请求，并在下一个可中断点识别取消、丢弃未提交结果且不更新工作集

#### Scenario: 取消处理中的调查 Run
- **WHEN** 用户在控制器或查询工具批次期间取消 investigate Run
- **THEN** Worker 在下一边界从最新数据库状态识别取消，保留已完成轮次审计但不进入下一轮、正常回答或工作集推进

#### Scenario: MySQL 长事务期间取消
- **WHEN** Worker 在 MySQL 执行长事务且另一请求提交取消
- **THEN** 后续步骤边界使用独立短会话看到最新取消状态并终止 Run

#### Scenario: 取消其他用户的 Run
- **WHEN** 用户请求取消无权访问的 Run
- **THEN** 系统返回 404 且不改变该 Run

### Requirement: 终态提交保持一致
系统 MUST 在同一事务中提交助手消息结果、Run 终态、可选 Investigation 终态与调查摘要、活动槽释放以及可选输出工作集版本；失败、取消、澄清或重复执行 MUST NOT 留下被当作正常事实回答或活动上下文的半成品状态，输出工作集只可包含最终有效引用实际使用的 Entry。

#### Scenario: 回答与工作集提交成功
- **WHEN** 调查停止、最终回答和引用通过校验且满足工作集推进条件
- **THEN** 系统原子写入助手消息、Run/Investigation 终态与摘要、新工作集版本并释放活动槽

#### Scenario: 回答提交成功
- **WHEN** quick 回答和引用通过最终校验
- **THEN** 系统原子写入助手消息、Run 结果与 `completed` 或 `partial` 终态、可选工作集版本并释放活动槽

#### Scenario: 澄清回复提交成功
- **WHEN** 上下文决策要求澄清
- **THEN** 系统原子写入澄清助手消息与 Run 终态，但不创建 Investigation 或输出工作集版本

#### Scenario: 发现但未引用的 Entry
- **WHEN** 调查搜索到 Entry 但最终回答没有有效引用使用它
- **THEN** 该 Entry 保留在调查审计中但不加入输出工作集

#### Scenario: 最终提交失败
- **WHEN** 数据库在提交助手回答、调查终态或新工作集时失败
- **THEN** 系统不暴露部分完成答案、不切换活动工作集，且 Run 可按恢复规则重试或失败

### Requirement: 分阶段 AI 可观测性
系统 MUST 为上下文决策/改写、回答模式路由、每轮调查控制器、embedding、重排、最终回答及每次工具调用保存阶段、provider、model、fallback 状态、错误、耗时与可选轮次/查询归属，并在 Run 上汇总用户可识别的降级、预算停止或异常状态；正常空结果 MUST NOT 误报为 fallback，工具部分失败或错误 MUST NOT 被记录为完全正常。

#### Scenario: 全阶段正常
- **WHEN** 路由、各轮控制器、embedding、重排和回答均由配置模型成功完成且工具正常
- **THEN** 各阶段记录实际 provider/model、轮次归属与 `is_fallback=false`，Run 无降级摘要

#### Scenario: 路由失败后 quick 成功
- **WHEN** auto 路由失败并按规则回退 quick，后续问答成功
- **THEN** 路由阶段记录 fallback/error，Run 返回实际模式 quick 且不得把整次执行标为完全正常

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
- **WHEN** 某轮搜索在当前范围正常完成但没有新 Entry
- **THEN** 工具记录 `empty`、调查以无进展停止且 Run 不把该空结果误报为模型 fallback

#### Scenario: 工具错误或部分失败
- **WHEN** 工具调用发生 error、denied、unavailable 或 partial
- **THEN** Run 汇总包含受影响轮次、查询、工具和原因且不得标记为完全正常

#### Scenario: 回答模型不可用
- **WHEN** 调查已有结果但最终回答模型未配置或调用失败
- **THEN** 系统明确记录回答阶段失败并将 Run 标为 `partial` 或 `failed`，不得伪装为正常 AI 回答

### Requirement: 知识问答使用 quick 或有界调查执行图
系统 MUST 在上下文决策后按实际回答模式执行 quick 固定单轮图，或执行由应用控制、服务端预算限制的调查循环；两条路径的事实均 MUST 只来自当前 Run 重新读取的正式 Entry 与 Evidence，模型 MUST NOT 自行创建无限工具循环。

#### Scenario: quick 继续追问正常完成
- **WHEN** Worker 领取一个有活动工作集的 quick `continue` Run 且各阶段成功
- **THEN** 系统合并复验后的工作集种子与新召回，生成本 Run Evidence、回答和可选新工作集版本

#### Scenario: investigate 正常完成
- **WHEN** actual mode 为 investigate 且调查在预算内完成若干轮
- **THEN** 应用逐轮执行固定只读工具链并用最终账本生成一次带当前 Run Evidence 的回答

#### Scenario: 新话题正常完成
- **WHEN** Run 决策为 `new_topic`
- **THEN** 系统不使用旧工作集种子，按当前独立问题执行所选回答模式；有有效引用时建立工作集版本，知识不足时可建立只含主题标签的空版本

#### Scenario: 历史消息不作为事实
- **WHEN** 同一对话提交 quick 或 investigate 追问
- **THEN** 有限历史只参与意图、路由与查询理解，回答事实仍只来自本 Run 重新读取的正式 Entry 与 Evidence

#### Scenario: 工具达到预算上限
- **WHEN** quick 工具或调查的轮次、查询、结果、Entry、Evidence 已达到服务端上限
- **THEN** 系统停止扩张并基于已有有效证据继续或明确标记知识不足与停止原因

