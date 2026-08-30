## Context

`add-native-knowledge-agent-conversation` 已把只读 Knowledge Agent 的 Conversation、Message、Run、Evidence、连续追问、受限调查与原生回答页接成真实纵向链路。现有旧 Web Reader 另有 `/api/projects/{project_id}/reader/save-candidate`：客户端提交问题、标题、内容和引用后，服务端创建虚拟 Source / Attachment / Extraction / Candidate，并同步执行目录路由和关系判断。该接口没有 Knowledge Conversation / Run 归属，也允许客户端重传引用，不能直接作为原生 Agent 的可信写操作协议。

移动原型已经展示更完整的「整理成知识 → 可编辑草稿 → 差异 → 确认修改 → 执行回执 → 撤销」路径，但其中包含正式 Entry 更新、重复项合并与撤销。首个写操作 change 只验证共同模型的前半段：显式发起 → 草稿 → 用户确认创建 Candidate。Candidate 仍要进入既有确认流程后才可能成为正式 Entry。

本 change 同时受以下约束：知识范围只到 Workspace / 项目；Workspace 回答可能引用多个项目；历史 Evidence 快照可展示但不必然仍可用于新写入；模型不得指定 Workspace、项目或任意对象 ID；SQLite 与 MySQL 均须支持幂等确认和恢复；原生页面严格按现有原型的视觉层级实现，但不得复制 HTML/CSS/演示脚本。

## Goals / Non-Goals

**Goals:**

- 在对话中跑通第一条低风险知识操作：从一条有有效引用的回答生成、编辑并确认 Candidate 草稿。
- 让操作请求、草稿生成、确认结果可持久化、可恢复、可审计、可幂等重试。
- 只使用服务端选定且重新校验的 Run Evidence 建立溯源，目标项目与权限由应用层控制。
- 复用现有 Candidate、虚拟 Source、目录路由与关系判断服务，避免建立第二套正式知识模型。
- 在原生 App 中清楚区分即时回答、AI 草稿、已创建 Candidate 与正式 Entry。

**Non-Goals:**

- 不修改正式 Entry，不实现合并、修订、移动、删除、目录写入、正式差异审阅或撤销。
- 不在移动端完成 Candidate 的最终归档确认，不复制桌面确认台。
- 不用自由文本自动识别任意写意图，不开放通用工具循环或模型直写数据库。
- 不删除旧 Reader，不迁移 Web 对话入口，不改变普通问答 Run 的默认执行图。
- 不引入联网、外部知识或跨项目综合写入。

## Decisions

### 1. 首版用显式结构化动作进入写分支

回答卡只在 `answer.status` 为 `completed` / `partial` 且存在最终有效 citation 时显示「整理成知识」。点击后客户端提交一条可见用户消息，同时带服务端枚举 `request_kind=draft_candidate` 与 `source_run_id`；Composer 的普通文本提交继续固定为 `request_kind=answer`。

这样既保持动作发生在对话里，又避免「这个回答能保存吗」之类讨论被模型误判成写操作。备选方案是新增自由文本意图路由，但首个写工具尚无误判数据，错误创建草稿会增加理解和恢复成本；待结构化路径有真实使用数据后再单独评估。

### 2. Candidate Draft 是独立持久对象，生成过程复用 Run 状态机

新增 `knowledge_candidate_drafts`，至少保存：workspace_id、owner_user_id、conversation_id、operation_run_id、source_run_id、target_project_id/name 快照、status、title、content、main_type、info_nature、evidence_handles_json、generation_meta_json、confirmed_candidate_id、created_at/updated_at。状态限定为 `generating`、`draft`、`confirming`、`confirmed`、`cancelled`、`failed`；`operation_run_id` 与 `source_run_id` 分别唯一约束到所属关系，确认结果只能写一次。

`KnowledgeAgentRun` 增加 `run_kind=answer|draft_candidate` 与可选 `source_run_id`。候选草稿 Run 继续占用单会话活动槽、支持 waiting / processing / failed / cancelled / completed、租约恢复和阶段可观测性，但不执行上下文决策、回答模式路由、搜索或调查，也不推进工作集。终态助手消息只保存面向用户的短说明；结构化草稿由 Message Page 的规范化 `candidate_drafts` 集合按 draft_id 返回，避免把可编辑状态塞入自然语言正文。

备选是纯同步 `POST /draft` 或只在客户端保存表单。它们实现较轻，但模型调用、断线恢复、历史重开和幂等性都会与现有 Agent Run 分裂，因此不采用。

### 3. 来源 Run 和目标项目必须由服务端确定

`source_run_id` 必须属于同一用户、Workspace、Conversation，处于可用终态，并至少包含一条最终 citation。项目范围回答直接固化该项目；Workspace 回答按最终 citations 统计项目：若只有一个项目可直接预填，若有多个项目则先由用户在 Workspace 项目列表中选择，服务端只向草稿生成器暴露该项目的 Evidence。

目标项目不能来自模型输出。服务端从 source Run 的最终 citation 句柄反查 `KnowledgeAgentEvidence`，只接纳 project_id 等于目标项目、Entry / Source / Attachment 当前仍存在且属于同一 Workspace、quote 与内容指纹仍可核验的 Evidence。目标项目没有可用 Evidence 时返回可恢复的 409，不创建 operation Run 或 Draft。

### 4. 草稿模型只组合 Evidence 支持的内容

草稿阶段使用独立 PydanticAI 结构化输出：title、content、main_type、info_nature、selected_evidence_handles。输入包含原问题、原回答（仅作编辑上下文）、目标项目标签和受限 Evidence 原文；模型只能从服务端给出的句柄中选择，不得输出项目、Workspace、Source 或 Entry ID。

应用层校验句柄属于本次允许集合、去重且至少一条有效。模型失败时不伪装成功：记录 provider/model/fallback/error；可采用确定性降级，把原回答的可支持部分作为可编辑 seed 并显式标记“草稿生成已降级”，也允许用户重试。无任何有效 Evidence 时必须失败，不能用原回答或模型常识创建无来源草稿。

### 5. 编辑不改证据，确认时再次核验并幂等创建 Candidate

用户可 PATCH title、content、main_type、info_nature；首版不允许客户端编辑 Evidence 句柄、目标项目或 source Run。取消只把 Draft 标为 `cancelled`，不创建 Source / Candidate；已 confirmed 的 Draft 不可编辑或取消。

确认接口以 Draft id 和稳定 `client_operation_id` 执行。事务内锁定 Draft，重验 owner / Workspace / project / Evidence 与正文非空；首次确认创建虚拟 Source、包含原问题、原回答、编辑后草稿与来源 Run 标识的文本 Attachment、Extraction 和 pending Candidate，并写回 `confirmed_candidate_id`。相同 idempotency key 或 confirmed Draft 返回同一 Candidate；不同并发确认不得创建重复 Source。历史 Evidence 若已失效返回 409 并保持 Draft 可编辑/可重新生成，不用快照冒充当前来源。

Candidate 的 `evidence_refs` 由服务端 Evidence 的当前 attachment_id/quote 构造。确认事务后复用既有 `route_source` / `route_relations`；某一步失败必须记录并让 Candidate 保持 `routing_status` / `relation_status` 的真实待处理或失败语义，不回滚已经成功创建的待确认 Candidate，也不把该阶段显示为正常。是否将两项完全异步化不在本 change 扩展；优先复用现有实现，只有测试证明确认延迟不可接受时再记录后续优化。

### 6. 旧 Reader 与新协议共用应用服务，不互相代理

从 `services/reader.py` 抽取“已校验输入 → 创建虚拟 Source / Attachment / Extraction / Candidate”的内部服务。旧 Reader 端点继续负责校验其旧 request，Knowledge Agent 确认接口负责校验 Draft/Run/Evidence；两者仅在校验完成后调用共享创建服务。不得让新接口调用旧 HTTP 端点，也不得让旧客户端获得 source Run 能力。

### 7. 原生界面采用原型层级，并明确裁剪

视觉基线来自 `docs/prototypes/grove-mobile-agent-prototype.html`：回答卡下的结构化后续动作、Agent 标签、`AI 建议 · 待确认` 语义、卡片内标题/核心内容字段、固定层级的 Sheet、确认说明和执行回执。正式 React Native 使用现有 `Card`、`AppButton`、`Badge`、`AgentIcon`、主题令牌和原生输入组件重建，不复制内联样式。

本 change 的有意偏离：

- 原型的草稿针对“更新主 Entry + 合并重复项”，正式实现改为“创建待确认 Candidate”，因此不展示保留/补充/替换/合并计数。
- 不打开「审阅完整差异」全屏页，不显示正式 Entry 影响对象，也不提供“确认合并”与撤销；改为编辑 Sheet +「创建待确认知识」确认 Sheet。
- 成功回执写“已创建待确认知识，尚未写入正式知识”，提供查看来源摘要与继续对话；移动确认台未接入前不伪造“去确认台”可用入口。
- 项目范围沿用当前项目；Workspace 多项目回答在生成草稿前使用项目选择 Sheet，目录不进入范围选择器。

主视口 390×844，扩展验证 360×800 与 412×915；草稿长文本、键盘、多行输入、项目 Sheet、确认 Sheet、失败重试和历史恢复均不得被顶栏、Composer、底栏或系统键盘遮挡。项目选择和所有主要动作满足 44×44 触控目标与读屏标签。

### 8. 客户端以服务端 Draft 为权威并做未知结果恢复

移动端扩展 Message Page / Run 适配器，把 Draft 归并到相应 operation Run。生成中沿用活动 Run 轮询；终态后 refetch 消息页与 Draft。编辑使用 mutation 后更新权威 Draft；确认超时不重复创建本地回执，而是复用 `client_operation_id` 查询/重放并以 `confirmed_candidate_id` 为准。

App 进入后台停止轮询，恢复前台立即 refetch；重启或切换会话从服务端历史恢复 generating/draft/confirmed/failed 状态。范围切换不重写旧 Draft 的项目快照；未确认 Draft 仍可查看，但若用户想在新范围继续，必须新建操作，不能偷换目标项目。

### 9. 原型视觉基线提取（grove-mobile-agent-prototype.html）

按原型「整理成知识」路径提取并在正式 React Native 中复现的视觉基线：

- 卡片：`border 1px #DDE3DF`、圆角 10、`card-body padding 13`、标题 16/700、正文 13–14/行高 21–23；
- AI 语义：`AI 建议` Badge 使用 ai 色（`#7251A5`/`#F2EDF8`），卡片可带 `border-left 3px ai`；本 change 文案固定为「AI 草稿 · 未创建候选」；
- 结构化后续动作：回答卡引用条与范围印记之后的全宽 AI 操作按钮（`#DACCDE` 边框、`#F2EDF8` 底、`#7251A5` 文字，min-height 44）；
- Sheet：底部弹层圆角 18、把手 36×4、标题 17/700、`sheet-body padding 16/18`、`confirm-box` 圆角 9；
- 确认回执：`receipt-icon 34×34` 圆角 8 confirmed 色、`receipt-row min-height 40` 列表、成功文案「已创建待确认知识 · 尚未写入正式知识」；
- 主按钮 min-height 44、圆角 8、primary 为绿色 `#236748` 白字；禁用态 opacity 0.48。

有意偏离（与第 7 节一致）：不展示保留/补充/替换/合并计数、不实现「审阅完整差异」全屏页、不显示正式 Entry 影响对象、不提供确认合并/撤销；编辑与确认收敛为可滚动 Sheet，成功回执只表达 Candidate 待确认。

正式代码只复用 `Card`/`AppButton`/`Badge`/`Sheet`/`AgentIcon` 与 `theme` 令牌，不复制原型内联 CSS、HTML 或演示脚本。

## Risks / Trade-offs

- [用户以为一次确认就已成为正式知识] → 全流程使用“AI 草稿”“创建待确认知识”“尚未写入正式知识”，回执显示 Candidate 状态，不使用“已归档”。
- [Workspace 回答跨项目，草稿混入其他项目事实] → 先选目标项目，只把该项目的最终 Evidence 暴露给模型，确认时再校验。
- [历史 Evidence 可展示但当前来源已删除或变化] → 生成和确认均重新核验当前 Entry / Source / Attachment / 指纹，失效时 409 并提供重新生成。
- [模型将原回答中的无证据总结写入草稿] → 结构化句柄白名单、Evidence-only prompt、用户编辑确认和 Candidate 二次确认共同约束；不把草稿升级为正式 Entry。
- [新增 Draft + Run 使状态复杂] → 使用独立状态机与一对一关系，普通回答默认路径不变；测试覆盖取消、崩溃、并发确认与重放。
- [创建 Candidate 后路由/关系判断较慢或失败] → 复用现有服务并暴露真实 pending/失败结果；不因辅助建议失败丢失 Candidate，真实延迟出现后再单独异步化。
- [原型视觉与裁剪后的业务不一致] → design 明确保留的视觉层级和有意偏离，验收同时对照原型与当前规格，不实现未进入本 change 的模拟状态。

## Migration Plan

1. 新增 Draft 表、Run kind/source_run_id 字段和必要索引/唯一约束；迁移默认既有 Run 为 `answer`，不回填 Draft。
2. 先上线后端模型、共享 Candidate 创建服务、API 与 Worker 分支；旧 Reader 行为和响应保持兼容。
3. 再上线原生类型、controller 与界面；不支持新字段的旧客户端仍只发送 answer Run。
4. 回滚客户端时隐藏动作入口即可；回滚后端前先停止创建 draft Run，再回退迁移。已确认 Candidate/Source 作为真实待确认数据保留，不随功能回滚删除。

## Open Questions

- 无阻塞问题。自由文本操作意图、Candidate 最终确认、正式 Entry 修改/合并/撤销和路由异步化均明确留给后续 change，以真实使用数据决定顺序。
