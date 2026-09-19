## Context

正式 Worker 已只走统一 dialogue loop，并在 Run 响应中公开 `dialogue_loop_status`、处理中 `dialogue_stage`、有序 `dialogue_blocks`、`can_continue` 和不透明 `continuation`。原生端仍围绕旧 `answer/citations/entry_result` 与两类持久草稿组织类型、控制器和界面，导致正式回答退化成扁平文本，且大量不可达写逻辑继续占据运行时模块。

本设计采用用户确定的方案二：保留原生基础设施和一致的交互基线，替换知识对话业务模块，不保留新旧双轨。依据与删改范围来自本 change 规格及 `docs/discussions/移动端知识Agent现状与对齐摸排-2026-09-18.md`，其中“恢复旧 Candidate/Revision 入口”等建议已被本轮产品决定替代。

## Goals / Non-Goals

**Goals:**

- 以正式 dialogue 合同恢复当前 Conversation 的历史、阶段、终态、块和 continuation。
- 用现有原生主题与基础组件展示正式块，并让明确 Entry 列表通过底部只读详情按需读取当前正文。
- 从移动运行时代码中删除旧 Candidate Draft、Entry Revision、citations、旧 Entry Result 和未生效模式业务。
- 保留登录、Bearer、安全存储、会话/消息分页、范围、消息幂等、前台轮询、取消、前后台及重启恢复。

**Non-Goals:**

- 不修改共享 loop、提示词、预算、模型、工具、Candidate/Revision 服务或数据库。
- 不增加写操作、Operation Review、能力感知、第二套记忆或客户端关键词路由。
- 不实现移动收集、待处理、知识主页面，不迁移或删除测试数据。
- 不重设计 App 壳层，不升级依赖，不用模拟器或真机替代用户验收。

## Decisions

### 1. Run 类型保留服务端兼容外形，移动业务只处理普通对话

移动端 `KnowledgeRun` 继续允许服务端返回兼容字段，但 UI 和控制器只把普通回答 Run 作为正式对话内容；消息页即使仍携带 `candidate_drafts` 或 `entry_revision_drafts`，客户端也忽略，不建立 map、不轮询、不恢复卡片。这样不要求后端为单一客户端改变消息页，同时真正删除移动写业务。

备选是修改后端按客户端裁剪响应；它会扩大共享合同并无助于本轮用户价值，故不采用。

### 2. 使用小而明确的 block 联合类型与本地防御性读取

在移动类型层声明正式已知块及公共字段，同时允许 `unknown` kind 的安全占位。渲染器按数组原序逐块输出，不按类型分组：

- `text`：普通即时回答文本；
- `list`：按 `result_type/semantics.subject` 区分 projects、directories、entries；只对 entries 中带数值 `entry_id` 的项开放正文读取；
- `statistic`：展示服务端 value/buckets/completeness，不由客户端重算；
- `entry`：展示回答生成时已读取的正文快照，不再重复请求同一内容；
- `evidence`：只按公开 `text/entry_id/source_id` 表达本轮核验材料，不拆自然语言；
- `candidate` 与兼容 `candidate_text_only`：统一显示“AI 候选稿/修改建议 · 未应用”；
- `insufficient`：显示材料不足边界；
- 未知/无效块：单块占位，其余块继续显示。

存在至少一个可展示块时不渲染完整扁平 answer；无块时只显示简单文本回退，不恢复 points、citations、conflicts 或 answer_basis。

备选是复制 Web renderer。Web 的 DOM 结构和执行记录不适合原生端，而且会把桌面布局带入移动；本轮只复用合同判断，不复制实现。

### 3. Entry 列表使用紧凑行与底部只读详情

本决定替代此前“原位展开正文”。知识列表按服务端原序保留序号，以标题为主，项目与目录归属独立紧凑展示；正文 `summary/excerpt` 最多一行，关联性质与 `relevance_reason` 独立表达，不把归属、摘要和关联说明拼成一段。只有 list 语义为 entries 且列表项带数值 `entry_id` 时可打开详情，项目和目录项不可误接 Entry API。

点击可读项后才挂载详情查询，沿用现有 TanStack Query key 与 `getEntryCurrent`。详情使用现有 Sheet 基础结构的局部 `slide` 动效变体，系统启用减少动态效果时关闭动效，不改变 History、Scope 与上下文 Sheet。详情负责加载、失败重试、当前不可访问、标题、当前正文、更新时间和当前来源摘要；正文使用正常阅读字号与行距，长内容在 Sheet 内滚动，关闭、遮罩和系统返回都只关闭详情并保留主对话滚动位置。

详情固定表达“当前知识内容”和“当前知识的来源信息”，Entry block 仍表达“本轮读取的知识正文”，Evidence block 仍表达本轮核验材料。打开详情只触发单个 Entry GET，不提交消息、不调用模型、不注入 Agent 上下文，也不恢复旧引用、修订或候选保存流程。

### 4. continuation 复用普通消息提交管线

继续按钮只渲染在其所属 Run 卡上，并由控制器验证该 Run 属于当前 Conversation、是会话 `recent_run_id` 指向的最新可恢复 Run（旧响应无该字段时退回当前已加载页中更新时间最新的可恢复 Run）、`can_continue=true` 且没有活动 Run。点击后通过现有 pending submission 管线发送正文“继续”，生成新的 `client_message_id`；客户端不读取、复制或修改 `continuation`。

网络结果未知仍重放 pending submission 的原键；失败后重新提问与 continuation 都新建键。会话切换清除本地按钮动作上下文，显示完全由新 Conversation 的服务端页决定。

### 5. 只保留 context_mode 设置

`ModeSelection` 收敛为 `contextMode`；提交 API 仅显式发送当前后端有准确语义的 `context_mode`。后端 schema 的兼容默认值无需改动。快速/深度、结果形式、basis、source_run_id 纠正状态和所有对应 chip/测试删除。

备选是继续提交 auto 占位字段但隐藏 UI；这会保留误导性业务模型和未来双轨入口，不符合“删除不再使用的旧实现”。

### 6. 不修改后端

本轮展示所需的状态、块、continuation 和 Entry 当前只读接口均已存在。Evidence 的公开字段不足以重建旧引用 Sheet，但本轮明确禁止重建 citations 或从文本解析元数据，因此不是阻塞项。若后续产品需要 Source 标题、quote、附件或历史快照的独立交互，应另立后端 typed Evidence 合同 change。

### 7. 历史页与异步回调绑定会话代次

`olderPages` 按请求返回顺序保存为“较近旧页 → 更早旧页”，组合线程时也按该顺序逐页前插，使消息保持时间正序并让最终游标来自最早已加载页。页间消息仍按 id 去重，Run 仍按更新时间归并。

分页、范围切换和取消等会写入共享本地状态的异步请求在发起时记录 Conversation 与本地会话代次；切换会话、新建对话或重置当前对话状态时同步推进代次。迟到响应可以更新其自身服务端查询缓存，但不得再改写当前页面的旧页、Run、loading、busy、cancelling 或错误状态。普通消息提交因 pending 期间禁止切换会话，继续沿用既有幂等提交边界。

### 8. 顶部入口恢复稳定的三段职责

顶部左侧恢复不可点击的 G 品牌标识，中间使用可点击的当前知识范围，右侧使用具有辅助名称的对话历史入口；移除占据中间区域的重复“知识 Agent / 会话标题”。History Sheet 继续提供明显的新建对话入口。范围、历史和新建分别调用现有控制器能力；“继续当前主题 / 新话题”只属于下一条消息的 `context_mode`，不创建、替换或切换 Conversation。

### 9. 提交状态区分进行中与结果未知

pending submission 仍是幂等数据载体，但增加独立 UI 状态区分 `in_flight` 与 `result_unknown`。首次提交与恢复重试进入 `in_flight`，只显示普通用户消息发送态并禁用重复发送/恢复；只有网络、超时或其他无法确认请求是否到达服务端的错误进入 `result_unknown`，才显示持久恢复入口。恢复调用复用 pending 中原 Conversation、文本、上下文设置和 `client_message_id`。

401、404、409、校验错误等确定性响应清除 pending 并沿用现有明确错误语义，不显示结果未知。服务端 5xx 是已收到的确定失败响应，也不伪装成结果未知；用户可修改后重新发送并获得新标识。此区分只改变客户端状态表达，不改变 API 或服务端幂等合同。

### 10. 初始定位使用会话键与布局就绪双门禁

页面为当前 Conversation（或用户显式新建的 draft）保存一次性初始定位键。首次进入或显式切换后，在最新消息查询结束且内容完成布局时执行一次无动画 `scrollToEnd`；若布局事件先到则等待数据，若数据先到则等待布局，不使用无限定时器或反复延迟。

初始定位完成后，内容更新只有在用户仍接近底部时才跟随；显式发送新问题会主动请求下一次内容布局跟随，以确保发送反馈可见。用户上滑或加载更早历史时禁用跟随并通过既有高度差锚点保持阅读位置。打开/关闭 Entry 详情和普通前后台恢复不重置会话键，因此不改变原阅读位置。

### 11. 活动 Run 使用紧凑过程行

活动 Run 保留 Agent 标识行，在其旁边或下一行显示一个小型 ActivityIndicator 与唯一的真实阶段文案；不再把阶段放入带阴影的大 Card，也不重复显示范围。取消入口位于右侧，使用中性停止图标和至少 44×44 触控区域，提供明确辅助名称；取消中禁用重复操作并显示“正在取消”。

轮询错误和取消失败仍在该 Run 附近持久展示并提供适用恢复动作。终态由 AnswerCard 展示并停止动效。ActivityIndicator 使用系统原生动效；减少动态效果设置交由平台处理，客户端不添加自定义循环动画或伪进度。

## Risks / Trade-offs

- [旧测试 Run 没有 blocks 时信息减少] → 只保留扁平文本回退；移动端尚未上线，接受不恢复旧复杂交互。
- [公开 list item 为弱类型字典] → 仅使用经类型守卫确认的字段，未知对象只读展示或占位，绝不据此发起写操作。
- [Entry 当前内容与历史块不同] → 底部详情与历史块分别标注“当前知识内容”和“本轮读取/生成时结果”，不覆盖历史块。
- [Sheet 切换为滑入影响其他弹层] → 只给 Entry 详情传入局部动画类型，通用 Sheet 默认仍为 fade；减少动态效果时详情使用 none。
- [初始定位与历史阅读竞争] → 以会话键只执行一次，并沿用加载旧页的高度锚点；前后台恢复和关闭详情不重置定位键。
- [旧 operation Run 仍出现在消息页 runs] → UI 不渲染其草稿或写回执；普通正式回答 Run 的恢复不受影响。
- [真实 continuation 不易稳定触发] → 用确定性控制器/组件测试覆盖，真实调用记录为未自然覆盖，不反复消耗模型制造失败。

## Migration Plan

1. 先提交完整 OpenSpec 工件并通过全库严格校验。
2. 新增正式 block 类型、渲染和 Entry 按需读取；改造阶段/终态与 continuation。
3. 收敛提交设置与线程状态，删除 Candidate/Revision/citation/旧 Entry Result 业务及专用测试。
4. 更新产品端侧专题、移动测试与本地讨论交付记录。
5. 运行移动端相关测试、typecheck、lint、OpenSpec 严格校验和 `git diff --check`；在已有服务和凭据可用时做少量真实正式链路检查，不启动或重启服务。
6. 本地提交后等待用户设备验收；未验收前不归档、不推送、不合并。

回滚使用 Git 恢复本 change 的移动端提交；不涉及数据库迁移或业务数据回滚。

## Open Questions

无阻塞产品问题。Evidence 若未来需要独立 Source 快照详情，必须另行决定 typed 后端字段与交互范围，不在本 change 内预留双轨。
