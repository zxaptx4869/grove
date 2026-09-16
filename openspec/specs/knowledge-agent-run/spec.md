# knowledge-agent-run Specification

## Purpose
一次只读问答的持久化 Run：固定有限执行图、状态机与单会话串行，支持取消、崩溃恢复与分阶段 AI 可观测性。
## Requirements
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
Worker MUST 通过数据库原子操作领取待执行 Run，并记录领取时间与重试次数。Candidate 与 Entry Revision operation Run MUST 在既有重试上限内保持幂等恢复；普通 answer Run MUST 仅恢复尚未进入编排的领取阶段，或通过现有安全状态检查的统一 dialogue-loop 阶段。旧执行步骤、未知步骤、损坏状态和超过上限的 Run MUST 进入可解释的失败终态，不得被送入统一循环。

#### Scenario: 两个 Worker 竞争领取
- **WHEN** 两个 Worker 同时尝试领取同一个 `waiting` Run
- **THEN** 只有一个 Worker 获得执行权且不会提交两份助手回答或重复 operation 结果

#### Scenario: Worker 重启后恢复
- **WHEN** answer Run 在领取后、进入循环前退出，或统一 dialogue-loop 留下允许恢复的持久化状态并超过租约
- **THEN** 系统在重试上限内重新入队同一 Run，并继续使用统一循环

#### Scenario: investigation Worker 重启后恢复
- **WHEN** 历史 investigation answer Run 超过租约且停留在旧调查执行步骤
- **THEN** 系统将 Run 标记为 `failed`、释放活动槽并说明旧快照不可安全恢复
- **AND** 已有轮次与账本保持可读，不重放旧执行器或送入统一循环

#### Scenario: 旧执行快照停止恢复
- **WHEN** answer Run 在旧 context、basis、result-mode、investigation、composite、coverage 或 shared-graph 步骤超过租约
- **THEN** 系统将 Run 标为 `failed`、释放会话活动槽并记录旧快照不可安全恢复
- **AND** 系统不调用统一 dialogue-loop 接管该 Run

#### Scenario: operation Run 恢复
- **WHEN** Candidate 或 Entry Revision Run 超过处理租约且没有超过恢复上限
- **THEN** 系统继续按既有幂等规则重新入队同一 Run

#### Scenario: 超过恢复上限
- **WHEN** 同一 Run 连续超过允许的恢复次数
- **THEN** 系统将 Run 标记为 `failed`、释放会话活动槽并记录恢复失败原因

### Requirement: Run 可取消
系统 MUST 允许对话所有者取消 `waiting` 或 `processing` Run；Worker、统一 dialogue-loop 适配器、Candidate、Entry Revision 和只读搜索 MUST 通过能读取其他事务最新提交状态的短会话，在各自既有安全边界检查取消请求。取消后的模型或工具结果 MUST NOT 写成正常回答、正式知识或 operation 结果。

#### Scenario: 取消等待中的 Run
- **WHEN** 用户取消尚未领取的 `waiting` Run
- **THEN** 系统将其标记为 `cancelled`、释放活动槽且 Worker 不再执行

#### Scenario: 取消处理中的 Run
- **WHEN** 用户取消正在统一 dialogue-loop 中处理的 answer Run
- **THEN** 系统记录取消请求，并在下一个可中断点识别取消、丢弃未提交结果且不更新工作集

#### Scenario: 取消处理中的调查 Run
- **WHEN** 所有者请求取消仍处于 `processing` 的历史调查 Run
- **THEN** 系统保留取消入口及历史审计，并按既有取消收尾逻辑释放活动槽
- **AND** 不重新启动旧调查控制器、不进入下一轮调查或生成正常回答

#### Scenario: 取消 operation Run
- **WHEN** 用户取消正在生成 Candidate 或 Entry Revision 的 Run
- **THEN** Worker 在既有安全边界识别共享取消信号并进入 `cancelled`，不提交正式 Entry 变更

#### Scenario: MySQL 长事务期间取消
- **WHEN** Worker 在 MySQL 执行长事务且另一请求提交取消
- **THEN** 后续步骤边界使用独立短会话看到最新取消状态并终止 Run

#### Scenario: 取消其他用户的 Run
- **WHEN** 用户请求取消无权访问的 Run
- **THEN** 系统返回 404 且不改变该 Run

### Requirement: 终态提交保持一致
系统 MUST 在同一事务中提交助手消息结果、Run 终态、实际结果形态、综合回答或结构化 Entry 结果、服务端校验后的实际回答依据、可选 Investigation 终态与调查摘要、活动槽释放以及可选输出工作集版本；失败、取消、澄清或重复执行 MUST NOT 留下被当作正常回答、实际依据、结构化结果或活动上下文的半成品状态。输出工作集只可包含综合回答最终有效引用实际使用的 Entry，用户陈述、模型通用知识与结构化搜索命中不得作为工作集 Entry。

#### Scenario: 回答与工作集提交成功
- **WHEN** 调查停止、最终回答、引用与实际依据通过校验且满足工作集推进条件
- **THEN** 系统原子写入助手消息、Run/Investigation 终态与摘要、实际依据、新工作集版本并释放活动槽

#### Scenario: 回答提交成功
- **WHEN** quick 回答、最终引用与实际依据通过校验
- **THEN** 系统原子写入助手消息、Run 结果、实际依据与 `completed` 或 `partial` 终态、可选工作集版本并释放活动槽

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

### Requirement: 候选草稿使用受控 operation Run
系统 MUST 为已接受的 draft_candidate 请求创建 `run_kind=draft_candidate` 的持久化 Run，固化 source_run_id、目标项目和 Draft；该 Run MUST 复用单会话活动槽、领取、取消、租约恢复、终态提交和可观测性，但 MUST NOT 执行问答上下文决策、回答模式路由、搜索、调查或工作集推进。

#### Scenario: 草稿 Run 进入等待
- **WHEN** 合法显式整理请求被接受
- **THEN** 系统创建 waiting operation Run、generating Draft 和助手占位并立即返回

#### Scenario: 草稿 Run 正常完成
- **WHEN** Worker 生成并校验 Candidate Draft
- **THEN** 系统原子提交 completed Run、draft 状态、助手说明并释放活动槽，且不更新工作集

#### Scenario: 草稿 Run 取消
- **WHEN** 用户取消 waiting 或 processing 的 draft_candidate Run
- **THEN** 系统按既有取消边界停止模型结果提交，把 Run 标为 cancelled、Draft 标为 cancelled，不创建 Source 或 Candidate

#### Scenario: 草稿 Run 恢复
- **WHEN** Worker 中断后 operation Run 超过租约且未超重试上限
- **THEN** 系统恢复同一 Run/Draft 并安全重放生成步骤，不创建重复 Draft 或 Candidate

#### Scenario: 操作阶段可观测
- **WHEN** 草稿生成模型或确认工具成功、降级或失败
- **THEN** 系统分别记录 purpose、provider、model、fallback/error、耗时和受影响阶段，不把失败标为正常

### Requirement: Entry Revision 使用独立受控 operation Run
Knowledge Agent Run MUST 支持 `run_kind=entry_revision`，固化 source_run_id 与 target_entry_id，并复用单会话活动槽、waiting/processing/failed/cancelled/completed 状态、租约、重试、取消和阶段可观测性。该 Run MUST 只执行修订草稿生成分支，不执行 answer 上下文决策、搜索、调查或工作集推进。

#### Scenario: Worker 执行修订 Run
- **WHEN** Worker 领取 waiting 的 entry_revision Run
- **THEN** 它校验关联 Draft 后执行 Evidence 复验与草稿模型，原子提交 Draft/Run/助手消息终态

#### Scenario: 修订 Run 崩溃恢复
- **WHEN** Worker 在模型调用边界退出且 Run 超过租约
- **THEN** 系统在重试上限内恢复同一 Run 与 Draft，不创建第二个 Draft 或重复消息

#### Scenario: 取消生成中的修订
- **WHEN** 用户取消 waiting/processing 的 entry_revision Run
- **THEN** Worker 在安全边界停止，Run/Draft 进入 cancelled，不修改 target Entry 或推进工作集

### Requirement: 修订生成与执行阶段可观测
系统 MUST 分别记录 entry revision 草稿模型、确认工具和撤销工具的 purpose、provider、model、fallback、error、duration 与结果摘要；响应成功 MUST NOT 掩盖模型降级、版本冲突、Evidence 失效或工具失败。

#### Scenario: 草稿模型成功
- **WHEN** entry_revision Run 生成合法草稿
- **THEN** 模型调用记录包含真实 provider/model/is_fallback/error 与耗时，Run 汇总可识别未降级成功

#### Scenario: 确认或撤销失败
- **WHEN** Entry 应用或撤销工具失败
- **THEN** 工具调用记录标记 error/真实状态，Execution 与界面不进入伪成功终态
