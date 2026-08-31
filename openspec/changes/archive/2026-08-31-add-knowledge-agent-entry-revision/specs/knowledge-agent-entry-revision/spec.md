## ADDED Requirements

### Requirement: 单 Entry 修订只能从明确目标显式发起
系统 MUST 只接受锚定同一 owner、Workspace 与 Conversation 内 `completed` 或 `partial` 回答 Run 的显式 `revise_entry` 请求；target Entry MUST 出现在该回答最终有效 citations 中，修订指令 MUST 非空。普通问答消息 MUST NOT 因文本看似包含修改意图而自动进入写分支。

#### Scenario: 从最终引用 Entry 发起
- **WHEN** 用户从回答引用详情选择一条 Entry、填写修订指令并确认发起
- **THEN** 系统保存可见用户消息并创建锚定 source Run 与 target Entry 的 revision operation Run

#### Scenario: 目标未被最终回答引用
- **WHEN** 客户端提交同项目但未出现在 source Run 最终 citations 中的 target_entry_id
- **THEN** 系统拒绝请求且不创建 Revision Draft 或 operation Run

#### Scenario: 普通消息讨论修改
- **WHEN** 用户通过普通 Composer 询问“这条是否需要修改”且未提交结构化 revise_entry 动作
- **THEN** 系统仍按只读回答处理，不创建修订草稿或修改 Entry

#### Scenario: 指令为空
- **WHEN** 用户未说明希望如何修订
- **THEN** 客户端阻止提交或服务端返回校验错误，不让 Agent 自行猜测修改目标

### Requirement: Revision Draft 持久化且可恢复
系统 MUST 持久化 Revision Draft 的 owner、Workspace、Conversation、operation Run、source Run、target Entry/项目、用户指令、基线字段与指纹、基线版本、允许/采用 Evidence、候选字段、差异、模型元数据、状态和执行关联；状态 MUST 限定为 generating、draft、confirming、applied、cancelled、failed、undone，并按合法路径转换。

#### Scenario: 草稿生成中重启 App
- **WHEN** Revision Draft 仍为 generating 且客户端退出后重新打开 Conversation
- **THEN** 消息历史返回同一 operation Run 与 Draft，客户端恢复进度而不重复提交

#### Scenario: 草稿生成完成
- **WHEN** operation Run 成功生成并校验出有实际变化的修订草稿
- **THEN** 系统原子保存 Draft 内容、服务端差异、completed Run 与助手说明并释放会话活动槽

#### Scenario: 非法终态转换
- **WHEN** applied、undone 或 cancelled Draft 被请求改回 draft
- **THEN** 系统拒绝转换并保留执行与审计关联

### Requirement: 草稿模型只使用最终采用且当前有效的 Evidence
系统 MUST 只把 source Run 最终回答实际采用、属于 target Entry 项目且当前仍可核验的 Evidence 提供给修订模型；target Entry MUST 至少是其中一条最终 citation 的归属对象。模型只能从服务端允许集合选择句柄，MUST NOT 使用模型常识、联网材料、其他 Run Evidence、其他项目内容或不可核验历史快照补充事实。

#### Scenario: 合法单 Entry 修订草稿
- **WHEN** 模型基于 target Entry、用户指令、来源回答和允许 Evidence 返回合法字段及句柄
- **THEN** 系统保存可编辑候选草稿与实际 provider/model/is_fallback/error，Entry 保持不变

#### Scenario: 回答未采用的 Run Evidence
- **WHEN** source Run 账本中存在最终回答 points/citations/conflicts 未采用的可引用 Evidence
- **THEN** 该 Evidence 不进入允许集合，也不能被修订草稿或新来源关系采用

#### Scenario: 模型返回未知或跨项目句柄
- **WHEN** 模型选择其他 Run、其他项目、未最终采用或未知 Evidence handle
- **THEN** 系统丢弃非法句柄；剩余上下文不能支持有效修订时 Draft/Run 明确失败

#### Scenario: 模型服务不可用
- **WHEN** 修订模型未配置、超时、失败或输出非法结构
- **THEN** 系统记录 provider/model/fallback/error 并提供重试，不用确定性文案或原回答伪装成成功修订

#### Scenario: 没有实际差异
- **WHEN** 归一化后的候选字段与基线 Entry 完全一致
- **THEN** 系统不生成可执行 Draft，并说明当前没有形成修改建议

### Requirement: 用户可编辑、查看差异或取消未执行草稿
系统 MUST 允许 Draft 所有者在 draft 状态编辑候选 Entry 字段与 change_summary、查看服务端按 base snapshot 计算的字段差异，或取消 Draft；target Entry、项目、source Run、基线和 Evidence 句柄 MUST NOT 由客户端编辑。取消或离开界面 MUST NOT 修改 Entry、版本或来源。

#### Scenario: 编辑候选字段
- **WHEN** 用户修改标题、正文、类型、信息性质、适用条件、补充说明或变更摘要
- **THEN** 系统保存编辑值并返回相对原基线重新计算的 changed fields

#### Scenario: 篡改受保护字段
- **WHEN** 客户端尝试修改 target_entry_id、target_project_id、source_run_id、base fingerprint 或 Evidence handles
- **THEN** 系统拒绝请求且不改变 Draft

#### Scenario: 取消草稿
- **WHEN** 用户取消尚未应用的 Revision Draft
- **THEN** Draft 进入 cancelled 并保留审计，Entry、版本和 Evidence 关系不发生变化

### Requirement: 确认修订幂等且拒绝过期基线
系统 MUST 只在用户明确确认 draft 状态对象后，以稳定 client_operation_id 幂等执行；确认 MUST 重新校验 owner、Workspace、Conversation、项目、target Entry、source Run、selected Evidence 和非空差异，并比较 Entry 当前字段/节点指纹及最新版本与 Draft 基线。基线过期 MUST 返回 409 且不得覆盖较新 Entry。

#### Scenario: 首次确认合法草稿
- **WHEN** Draft 基线和 Evidence 仍有效且用户确认执行
- **THEN** 系统在一个事务中更新一条 target Entry、追加版本、补充去重 Evidence、创建 Execution 并返回已应用回执

#### Scenario: Entry 在草稿后被修改
- **WHEN** target Entry 的字段、节点或最新版本已不同于 Draft 基线
- **THEN** 系统返回 409、恢复 Draft 可编辑状态并要求重新生成，不修改当前 Entry

#### Scenario: Evidence 在确认前失效
- **WHEN** selected Evidence 对应 Entry、Source、Attachment、项目归属、quote 或内容指纹无法重新核验
- **THEN** 系统返回 409 并保留未应用 Draft，不用历史快照更新正式知识

#### Scenario: 网络未知后重试确认
- **WHEN** 首次执行已提交但响应丢失，客户端使用相同 client_operation_id 重试
- **THEN** 系统返回同一 Execution 与 Entry 结果，不重复追加版本或 Evidence

#### Scenario: 并发确认同一草稿
- **WHEN** 两个请求同时确认同一 Revision Draft
- **THEN** 数据库约束与条件状态转换保证最多执行一次，另一个请求返回同一结果或稳定冲突

### Requirement: 正式更新保留版本与来源溯源
系统 MUST 保留 target Entry 的全部既有 Evidence，只把 selected Evidence 中尚未存在的真实 Source/Attachment/quote 关系去重补入；字段修改、版本追加、Evidence 增量、Project Context 刷新调度、embedding 待更新标记、Draft 与 Execution 状态 MUST 在同一事务语义内完成。Execution MUST 保存 before/after 快照、指纹、版本和本操作真实新增的 Evidence 关系。

#### Scenario: 采用其他 Entry 的有效来源
- **WHEN** 修订草稿选用了同项目另一条最终 citation 的 Evidence 且目标 Entry 尚未关联该原文
- **THEN** 确认后目标 Entry 新增对应真实 Source/Attachment/quote 关系，原有来源保持不变

#### Scenario: Evidence 已经存在
- **WHEN** selected Evidence 与目标 Entry 现有来源关系等价
- **THEN** 系统复用现有关系，不创建重复 Evidence，也不把它记录为本操作新增关系

#### Scenario: 更新事务失败
- **WHEN** 字段、版本、Evidence、Execution 或状态写入任一步骤失败
- **THEN** 整个确认事务回滚，Entry 与 Draft 保持操作前一致且不返回成功回执

### Requirement: 本次修订可并发安全地撤销
系统 MUST 允许 Draft 所有者对 applied Execution 发起一次幂等撤销；只有 target Entry 当前字段指纹仍等于本操作 after fingerprint 且最新版本仍为本操作 applied version 时，系统才能恢复 before snapshot、删除仅由本操作新增的 Evidence 关系、追加 restored 版本并把 Execution/Draft 标记为 undone。审计记录 MUST 保留。

#### Scenario: 成功撤销未被后续修改的操作
- **WHEN** Entry 在本次 applied 后没有任何字段、节点或版本变化且用户确认撤销
- **THEN** 系统原子恢复操作前字段，删除本操作新增 Evidence，追加恢复版本并返回 undone 回执

#### Scenario: 应用后发生其他修改
- **WHEN** Entry 当前指纹或最新版本不再等于 Execution 记录的 applied 结果
- **THEN** 系统返回 409，不覆盖后续修改、不删除任何 Evidence，并引导用户使用版本历史处理

#### Scenario: 重复撤销
- **WHEN** 首次撤销已成功但响应未知，客户端使用同一键重试或再次读取已 undone Execution
- **THEN** 系统返回同一撤销结果，不重复追加恢复版本或删除关系

#### Scenario: 撤销事务失败
- **WHEN** 恢复字段、删除新增 Evidence、追加版本或更新状态任一步骤失败
- **THEN** 撤销事务整体回滚，Execution 继续为 applied，界面可重试且不得显示已撤销

### Requirement: 修订全链路隔离、可观测且不推进工作集
系统 MUST 对 Draft、Run、Execution、Entry、Project 和 Evidence 的每次读写执行 owner + Workspace 校验；越权对象统一返回 404。草稿生成、确认与撤销 MUST 记录实际模型/工具状态、耗时、fallback 和错误；entry revision operation Run MUST NOT 创建或推进 Conversation 工作集。

#### Scenario: 越权 target Entry 或 Draft
- **WHEN** 用户提交其他用户或 Workspace 的 source_run_id、target_entry_id、draft_id 或 execution id
- **THEN** 系统返回 404、不暴露对象存在性且不产生任何写入

#### Scenario: 写操作完成后的下一次提问
- **WHEN** Revision Draft 被应用或撤销后用户继续提问
- **THEN** 下一 answer Run 从当前正式 Entry 重新检索，不把 operation Run 的草稿或执行摘要当作事实工作集

#### Scenario: 工具失败可见
- **WHEN** 确认或撤销工具阶段失败
- **THEN** Run/Execution/响应记录 error 与真实终态，界面显示可恢复错误而不是成功文案
