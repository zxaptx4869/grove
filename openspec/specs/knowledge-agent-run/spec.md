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

### Requirement: entries Run 固化结构化查询计划与版本
系统 MUST 为启用结构化查询能力的 `actual_result_mode=entries` Run 持久化服务端校验后的计划、schema 版本、prompt 版本和计划模型可观测信息；计划字段对旧 Run保持可空。计划一经固化 MUST 在同一 Run 的重试、恢复和历史读取中保持不变，模型原始输出或非法参数不得作为可执行计划保存。

#### Scenario: 计划验证后持久化
- **WHEN** structured query planner 返回合法计划且服务端规范化成功
- **THEN** Run 在任何查询工具执行前保存规范化计划、版本和模型调用审计

#### Scenario: 历史 Run 没有查询计划
- **WHEN** 客户端读取本 change 上线前的 entries Run
- **THEN** API 继续返回旧 Entry 结果快照，查询计划字段为空且系统不猜测历史筛选或聚合

### Requirement: 结构化查询 Run 可取消和崩溃恢复
Worker MUST 在查询规划前后、每个确定性工具调用前后和最终提交前检查取消；恢复时 MUST 复用已固化计划和同 Run 中已提交的幂等工具结果，只重放未完成的只读步骤。取消、超出恢复上限或迟到工具结果 MUST NOT 形成正常 Entry 结果快照。

#### Scenario: 计划后 Worker 崩溃
- **WHEN** Worker 已提交规范化计划但尚未完成全部工具调用时退出
- **THEN** 恢复复用同一计划，按调用指纹复用已提交结果并继续未完成步骤，不再次调用规划模型

#### Scenario: 聚合执行期间取消
- **WHEN** 用户在 aggregate_entries 执行期间请求取消 Run
- **THEN** Worker 在下一个边界丢弃未提交的迟到结果，将 Run 标为 cancelled 并释放活动槽

#### Scenario: 重放只读查询
- **WHEN** 未完成 query_entries 在租约恢复后重放
- **THEN** 重放不修改正式 Entry，并生成同一计划语义下的结果或明确对象已变化/执行异常

### Requirement: 结构化查询终态原子提交且可观测
系统 MUST 在同一事务中提交 v2 Entry 结果快照、助手兼容消息、Run 终态和活动槽释放；每次规划与工具调用 MUST 按实际 provider、model、fallback、状态、完整性、错误和耗时进入 Run 可观测汇总。部分失败 MUST 保留合法结构化结果并标记 partial/unknown，成功响应不得掩盖规划降级或工具异常。

#### Scenario: 组合查询正常完成
- **WHEN** count、group_count 与 entries 输出都正常执行并通过结果预算校验
- **THEN** 系统原子提交同一 v2 快照与 completed Run，调用顺序和每个输出完整性可查询

#### Scenario: 规划降级后旧查找成功
- **WHEN** 结构化查询规划失败但既有有限语义查找成功
- **THEN** Run 可以返回兼容 Entry 列表，但 fallback 汇总标识 structured_query_plan 失败，结果不包含伪聚合或精确全集承诺

#### Scenario: 一个工具部分失败
- **WHEN** 聚合完成但 Entry 列表装配出现部分不可用对象
- **THEN** 系统保留可确认的聚合和合法 Entry，按各输出完整性标记 Run/结果为 partial 或 unknown，不提交相互矛盾的半份快照

### Requirement: quick Run 可以固化共享执行图状态
启用共享执行图的 quick 复合 Run MUST 保存与首次规范化计划绑定的版本化图、冻结预算和节点终态；图执行状态 MUST 继续受同一 Conversation 活动槽、Worker 领取、租约恢复、重试上限、取消和终态原子提交控制。旧 Run、未启用共享图的 Run 和已有 `CompositeAnswerExecution v1` MUST 继续按原记录读取与执行，系统 MUST NOT 为历史 Run 反向生成共享图。

#### Scenario: 新 quick Run 进入共享执行
- **WHEN** 复合回答与共享执行图开关均开启，Run 已固化合法 `CompositeAnswerPlan v1`
- **THEN** Worker 在任何图节点前保存图与预算，并继续使用原 Run 活动槽和取消状态，不创建第二个子 Run

#### Scenario: 旧 Run 没有共享图字段
- **WHEN** API、Worker 或历史分页读取迁移前完成的 Run
- **THEN** 共享图字段保持空且原 answer、执行快照、coverage、basis 和状态照常可读，不推断或执行新图

#### Scenario: 租约恢复复用图节点
- **WHEN** processing Run 租约超时且合法图中已有终态节点
- **THEN** Worker 在恢复次数上限内重新领取同一 Run、复用终态节点并继续 pending 节点；超过上限仍按既有规则失败并释放活动槽

#### Scenario: 开关回滚不改写进行中图 Run
- **WHEN** 部署关闭共享图开关时仍存在已经持久化图的 processing/waiting Run
- **THEN** 这些 Run 继续按各自固化图恢复，新 Run 才使用串行路径，系统不得让进行中 Run 整体重跑旧执行器

### Requirement: 共享图预算和取消在节点边界生效
系统 MUST 为共享图固化节点数、深度、工具调用、对象、Evidence、桶、并发、字节和总耗时预算，并在节点启动、结果接纳、检查点与终态提交前检查取消和剩余预算。并行执行不得因竞态重复消费额度或使实际总量超过 Run 固化上限；达到预算时保留合法结果并明确标记受影响节点和回答义务。

#### Scenario: 并行 ready 节点竞争剩余额度
- **WHEN** 多个 ready 节点的潜在对象或 Evidence 总量超过剩余 Run 预算
- **THEN** 调度器按稳定顺序预分配有界额度，只执行获准部分，并把未获额度节点标记为 limited/partial 而不是由完成先后决定结果

#### Scenario: 节点返回时用户已经取消
- **WHEN** 独立会话中的只读节点完成，但协调器在接纳前发现 Run 已请求取消
- **THEN** 该结果不写入图 state、Evidence、工具成功记录或正常回答，Run 按 cancelled 收尾

#### Scenario: 图快照达到字节上限
- **WHEN** graph 或 state 无法在保留节点身份、依赖、状态、完整性和必要句柄的前提下写入配置的 TEXT 字节预算
- **THEN** 系统显式失败或在图尚未开始时降级串行，不静默截断关键恢复信息后继续

### Requirement: 共享图保持 Workspace 隔离和只读副作用边界
共享图的每个节点 MUST 从父 Run 重新构造并校验 owner、Workspace 和可选项目范围；节点结果、fingerprint、复用与依赖 MUST 限于同一 Run。并行会话、恢复、去重和兼容物化 MUST NOT 跨 Workspace、项目或 Run 读取、关联或复用 Entry/Evidence，也不得获得知识写入权限。

#### Scenario: 相同查询存在于两个 Workspace
- **WHEN** 两个 Workspace 的不同 Run 使用完全相同的规范化查询和输出参数
- **THEN** 它们拥有不同范围绑定与图结果，任何节点、Entry、Evidence、result handle 或缓存都不能跨 Run 共享

#### Scenario: 项目范围图节点被并行执行
- **WHEN** 一个项目范围 Run 同时执行多个独立节点
- **THEN** 每个独立数据库会话只读取该 Run 固化项目内正式 Entry，其他项目和 Workspace 的对象不进入候选、结果或审计摘要

#### Scenario: 图结果被最终综合采用
- **WHEN** 图节点产生 Entry、Evidence、统计或列表并完成回答
- **THEN** 只有当前 Run 重新核验的 Evidence 和实际结构化结果可以进入回答依据，查询命中本身不创建或修改正式知识、Candidate、Draft、Operation 或事实工作集
