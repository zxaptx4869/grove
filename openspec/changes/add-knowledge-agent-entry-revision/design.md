## Context

`add-knowledge-agent-candidate-drafting` 已交付第一条低风险写操作：用户从有证据回答显式发起，生成可编辑草稿，确认后只创建 pending Candidate。它验证了结构化动作、operation Run、持久草稿、Evidence 复验和原生对话状态，但刻意不修改正式 Entry。

Grove 现有桌面能力已经支持单 Entry 人工编辑、AI 修订建议、最近 10 个版本快照和恢复；Candidate 关系流程也能把补充草稿应用到既有 Entry。这些路径由普通 Entry service 完成，尚未与 Knowledge Conversation、Run Evidence、移动原型中的差异审阅和操作回执连接。现有桌面 AI 修订还允许模型自身知识并通过虚拟 Source 沉淀，而 Knowledge Agent 阅读严格只使用知识库内 Evidence；两者不能直接共享提示词边界。

移动原型把“整理知识”演示为多 Entry 合并：先澄清影响对象，再编辑草稿、查看完整差异、确认执行、返回可撤销回执。该路径同时包含单 Entry 更新、重复标记、冲突保留、多对象事务和撤销。为了继续按一个纵向能力迭代，本 change 只抽取其中稳定的公共内核：明确目标的一条 Entry → 候选修订 → 单对象差异 → 用户确认 → 版本化更新 → 并发安全撤销。

本 change 开工时还需注意：上一轮审查的 Candidate 路由部分失败、结构化空要点状态和 Candidate 草稿 Evidence 范围问题由独立修复任务处理。实现分支开始开发前必须先吸收这些已合并修复，但不得把修复任务重新混入本 change。

## Goals / Non-Goals

**Goals:**

- 从 Knowledge Agent 回答的最终引用中明确选择一条 Entry，并通过结构化动作提交非空修订指令。
- 使用可恢复 operation Run 生成、持久化和历史恢复单 Entry 修订草稿，清楚区分正式 Entry、AI 草稿、已执行修改和已撤销操作。
- 只让模型组合来源回答最终采用且当前可核验的目标项目 Evidence；目标、范围、ID、版本与执行权限均由应用层决定。
- 用户可编辑候选字段并查看由服务端基线计算的字段差异；只有再次确认后才原子修改 Entry、追加版本与必要 Evidence。
- 对本次操作提供幂等、并发安全、保留审计的撤销；不得覆盖操作后的其他修改。
- 复用现有 Entry 版本、项目上下文刷新、embedding 更新和 Evidence 关系能力，不建立第二套正式知识模型。
- 原生实现严格采用移动原型的视觉层级和交互原语，并完整覆盖长内容、键盘、安全区、恢复、冲突和错误状态。

**Non-Goals:**

- 不实现自由文本写意图路由、任意写工具循环、模型自主执行或跨对象计划。
- 不创建新 Entry，不把 pending Candidate 在移动端最终归档，不合并/标记重复、不移动目录、不删除、不批量修改。
- 不使用模型常识、外部网络或 Discovery 补充修订事实；不改变桌面 AI 修订建议允许外部补充的既有语义。
- 不把整个桌面版本历史或确认台搬到移动端；只展示本操作需要的基线、结果和撤销冲突说明。
- 不迁移 Web Reader，不实现移动端其余三个栏目，不抽象通用撤销框架。
- 不处理 proposal 已列明的三个独立修复问题。

## Decisions

### 1. 只从最终引用的 Entry 发起显式结构化修订

`native-knowledge-agent-answer` 的引用详情增加“修订这条知识”。点击后打开轻量指令 Sheet，显示 Entry 标题、项目/目录和当前摘要；用户输入非空指令后，客户端提交可见用户消息与结构化字段：

```text
request_kind = revise_entry
source_run_id
target_entry_id
instruction
client_message_id
```

服务端要求 source Run 属于同一 owner、Workspace、Conversation，终态为 `completed` / `partial`，且 target Entry 出现在该回答最终 citations 中。Entry 自身决定 target project；Workspace 回答无需再次选择项目，但不得使用其他项目 Evidence 修改它。普通 Composer 仍固定提交 `request_kind=answer`，不会把“这条需要改吗”误判为写操作。

备选方案是让模型从自然语言中解析“第二条”并直接进入修改。该方案目标解析错误会触发正式知识风险，也缺少真实误判样本，因此留到结构化路径积累使用数据之后。

### 2. Entry Revision Draft 与 operation Run 独立持久化

新增 `knowledge_entry_revision_drafts`，至少保存：

```text
workspace_id、owner_user_id、conversation_id
operation_run_id（唯一）、source_run_id、target_entry_id、target_project_id
instruction、base_entry_json、base_entry_fingerprint、base_version_id/number
allowed_evidence_handles_json、selected_evidence_handles_json
title、content、main_type、info_nature、applicable_condition、note
change_summary、reason、generation_meta_json
status、execution_id、error、created_at、updated_at
```

状态限定为 `generating`、`draft`、`confirming`、`applied`、`cancelled`、`failed`、`undone`。`KnowledgeAgentRun` 增加 `run_kind=entry_revision`，继续复用活动槽、waiting/processing/终态、租约恢复、取消、助手终态消息和模型/工具可观测表；该 Run 不执行上下文路由、搜索或调查，也不推进 Conversation 工作集。

Message Page 规范化返回 `entry_revision_drafts` 集合并由消息引用 draft id，避免把可编辑字段塞进自然语言正文。App 重启、历史分页和前后台切换都从服务端恢复真实草稿与执行状态。

备选方案是直接调用现有无状态 `/entries/{id}/revision-suggestion`。它无法锚定回答 Run、恢复草稿、保证幂等或区分本轮 Evidence，因此不采用；底层 Entry 上下文格式和字段校验可以抽取复用，但不能通过内部 HTTP 调用。

### 3. 草稿 Evidence 只来自来源回答最终采用的目标项目证据

允许集合按以下顺序确定：

1. 从 source Run 最终 answer 的 points/citations 与 conflicts 收集实际输出句柄；
2. 反查该 source Run 的 `KnowledgeAgentEvidence`；
3. 只保留 target Entry 所属项目内、当前 Entry/Source/Attachment 仍存在、quote 与内容指纹仍可核验的行；
4. target Entry 自身必须仍存在且至少有一条最终引用指向它；允许集合中至少有一条当前有效 Evidence。

草稿模型输入为用户指令、目标 Entry 当前字段、原问题、原回答（仅编辑上下文）和允许 Evidence 原文。输出是字段全集、change_summary、reason 与 selected handles；句柄必须属于允许集合。模型不得使用 AI 自身知识，模型失败、空草稿、无实际差异或没有有效 Evidence 时不伪装成功，Draft/Run 进入明确失败或可重试状态。

这项决定有意不同于桌面 AI 修订建议的外部补充模式，也明确不采用 Candidate Draft 当前“整轮全部 Evidence”的兼容做法。Knowledge Agent 的语义是修订当前回答明确展示过的知识，不应引入用户不可见的调查材料。

### 4. 用户可编辑候选字段，差异由服务端基线确定

Draft 状态允许 PATCH `title`、`content`、`main_type`、`info_nature`、`applicable_condition`、`note` 和 `change_summary`；target Entry、项目、source Run、基线与 Evidence 句柄均受保护。服务端每次响应按 `base_entry_json` 与当前草稿确定性计算 changed fields，客户端不提交或信任 diff。

用户编辑属于明确的人工作者输入，可以修改候选文字；确认前界面持续展示 Entry 既有来源与本次采用 Evidence。首版不做逐句 claim grounding，但不允许模型或客户端替换受保护 Evidence 集合。

### 5. 确认以基线指纹做乐观并发，并复用 Entry 应用服务

确认接口接收 Draft id 与稳定 `client_operation_id`。应用层原子完成：

1. 锁定/条件更新 draft 为 `confirming`，保证同一 Draft 只执行一次；
2. 重新校验 owner、Workspace、Conversation、项目、Entry、source Run 与 selected Evidence；
3. 比较 Entry 当前可变字段 + node id 的规范化指纹与 `base_entry_fingerprint`，并核对最新 EntryVersion；不一致返回 409，把 Draft 恢复为可编辑并要求重新生成；
4. 应用用户确认后的字段；若无实际差异返回稳定冲突，不制造空版本；
5. 把 selected Evidence 对应的真实 Source/Attachment/quote 去重补充到目标 Entry，保留全部既有 Evidence；
6. 使用现有 Entry service 追加 `knowledge_agent_revision`（或向后兼容的 `ai_revision` + 明确来源元数据）版本、刷新 Project Context、标记 embedding 待更新；
7. 创建一次 `KnowledgeEntryRevisionExecution`，保存操作前/后字段快照、前后指纹、前后版本、由本操作新增的 Evidence 关系 id、client_operation_id、状态和时间；
8. Draft 进入 `applied` 并提交，随后返回正式 Entry 与可撤销回执。

优先把 Entry 字段应用、版本快照、Evidence 去重、上下文刷新与 embedding 标记收敛为可复用应用服务；Knowledge Agent 和现有桌面端分别完成各自输入校验后调用，不互相代理 HTTP，也不改变桌面外部知识规则。

### 6. 撤销是本操作的条件恢复，不是任意版本回退

执行记录状态限定为 `applied`、`undoing`、`undone`。撤销接口使用稳定 `client_operation_id` 并在单事务内：

- 校验 Draft/Execution/Entry 仍属于同一 owner 与 Workspace；
- 要求 Entry 当前字段指纹仍等于本次 `after_fingerprint`，且最新版本仍是本次 applied version；
- 恢复 execution 的 before snapshot；
- 只删除 execution 明确记录且仍属于目标 Entry 的新增 Evidence 关系，不影响既有或其他操作新增的来源；
- 追加 `restored` 版本、刷新 Project Context、标记 embedding 待更新；
- Execution 与 Draft 进入 `undone`，保留全部执行与撤销审计。

若 Entry 在应用后被人工编辑、移动、再次修订或恢复，撤销返回 409，不覆盖较新的正式知识；界面说明“知识后来发生了变化，请到版本历史处理”。相同撤销键或已 undone 状态返回同一结果，不重复追加版本。撤销失败不把 applied 操作伪装为 undone。

现有通用版本恢复端点仍保留；本 change 不把它包装成无条件撤销，因为它不知道本操作新增了哪些 Evidence，也缺少后续修改冲突语义。

### 7. 原生界面复用原型交互语法，但收敛为单 Entry

**原型基线**

- 对应页面：`docs/prototypes/grove-mobile-agent-prototype.html` 的可编辑知识草稿、`diffOverlay`、确认修改 Sheet、执行回执和撤销 Sheet。
- 主验收视口：390 × 844；扩展视口：360 × 800、412 × 915。
- 主题与组件：复用 `mobile/src/theme.ts`、现有 `AgentIcon`、Card/Sheet/Button、ConversationScreen、DraftCard 和消息归并模式；正式实现不得复制原型 HTML、CSS 或演示脚本。
- 关键状态：指令输入、生成中、草稿、编辑、完整差异、确认、执行中、已应用、撤销确认、已撤销、版本冲突、Evidence 失效、生成/执行/撤销失败与重试。

**采用的结构**

- 引用详情 Sheet 中以 Entry 为明确目标提供修订动作；指令 Sheet 先显示目标和后果，再提交可见用户消息。
- 对话内修订草稿卡显示“AI 建议 · 待确认”、目标项目/目录、字段摘要和“编辑并检查”。
- 编辑 Sheet 处理键盘与长字段；完整差异使用全屏审阅，按改变的字段展示“原内容 / 建议内容”，未改字段默认折叠。
- 确认 Sheet 明确“将更新 1 条正式知识、追加版本、保留既有来源、可在未发生后续修改时撤销”。
- 回执区分“已更新正式知识”和“操作已撤销”，提供查看 Entry、查看差异和撤销；失败留在原位置并提供恢复动作，不只用 toast。

**有意偏离**

- 不显示“保留/补充/替换/准备合并”多对象计数，只显示发生变化的字段数量与新增来源数量；原因是本 change 只有单 Entry。
- 不显示重复/冲突 Entry 影响对象，不提供“确认合并并标记重复”；原因是多 Entry 操作明确后置。
- 执行过程收敛为“校验当前版本 → 更新 Entry 与来源 → 保存版本”三项可验证阶段，不伪造模型思考。
- 撤销在存在后续版本时不可用并展示冲突说明，不演示无条件恢复；原因是正式数据并发安全优先于原型的确定性演示。
- 不从普通文本自动识别写意图；修订必须从 Entry 目标动作发起。

视觉实现前需提取原型对应组件的元素顺序、间距、徽标、按钮和层级写入 validation 基线；完成后必须使用真实 RN 页面在三尺寸检查截图、系统键盘、安全区、长正文滚动、动态字体、44×44 触控和读屏标签。Expo Web 只能作为补充，不能替代 iOS/Android 验收。

### 8. 可观测性与历史协议延续现有 Run 模型

草稿生成记录 `entry_revision_draft` 模型阶段；确认和撤销分别记录工具调用，包含 draft/execution/entry id、结果状态、版本号、Evidence 增量和错误摘要，不记录隐藏推理。响应与界面可识别 provider/model/fallback/error；模型不可用不得返回成功草稿。

operation Run 不推进工作集，避免一次写操作改变后续指代主题。写入或撤销成功后客户端失效相关 Entry、项目知识、版本、引用详情和 Conversation history 查询；后续问答仍会从正式 Entry 重新检索。

## Risks / Trade-offs

- [用户编辑草稿后可能写入 Evidence 未逐句支持的表述] → 明确显示来源与人工确认，保留操作指令/差异/版本审计；首版不承诺逐句 grounding，后续基于真实样本评估。
- [版本表只保留最近 10 条] → Execution 自身保存 before/after 快照，不依赖旧版本长期存在；撤销仍要求没有后续修改。
- [EntryVersion 的 `max + 1` 在高并发下可能冲突] → 确认/撤销通过 Draft/Execution 条件更新和 Entry 基线冲突拦截；测试同时覆盖 SQLite 与 MySQL 约束语义，必要时在服务内稳定转为 409。
- [Evidence 关系没有现成唯一约束] → 应用服务按规范化 `(entry_id, source_id, attachment_id, quote)` 去重，并记录本操作真实新增的关系 id；并发重复由事务内查询与测试约束，是否新增数据库唯一索引在实现 spike 后决定。
- [撤销和后续编辑竞争] → 使用 after fingerprint + latest version 双重校验；宁可拒绝撤销，也不覆盖更新内容。
- [新增 Run 类型继续扩大单体 runner] → 复用 operation 分派但把 Entry 修订实现放在独立 service/agent 模块；本 change 不抽象通用写工具框架。
- [完整差异页增加移动实现量] → 单对象差异是用户确认正式写入的必要安全界面，复用现有 Sheet/Overlay 原语，批量影响页仍后置。

## Migration Plan

1. 新增 Alembic 迁移创建 Revision Draft 与 Execution 表、约束和索引；现有 Conversation/Run 数据无需回填，Run 类型保持向后兼容默认值。
2. 先部署后端模型、服务与兼容响应，再发布原生客户端；旧客户端忽略新增集合和 request kind，不受影响。
3. 若回滚客户端，只隐藏新动作；后端保留历史 Draft/Execution 供审计，不删除已应用 Entry 版本。
4. 若回滚后端，先停止新 entry revision Worker 分支；迁移 downgrade 仅在确认不需要历史恢复时删除新表，已应用 Entry 与版本不得自动反向修改。

## Open Questions

- 无阻塞产品问题。实现阶段需用 SQLite/MySQL spike 决定 Evidence 去重采用应用层锁定还是新增兼容唯一索引，但不得改变“只记录本操作真实新增关系、撤销不删除既有来源”的规格语义。
- 原型中多 Entry 合并、冲突保留和分步确认留给下一 change，不在本次根据字段预留提前实现。
