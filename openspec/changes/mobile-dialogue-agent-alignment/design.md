## Context

正式 Worker 已只走统一 dialogue loop，并在 Run 响应中公开 `dialogue_loop_status`、处理中 `dialogue_stage`、有序 `dialogue_blocks`、`can_continue` 和不透明 `continuation`。原生端仍围绕旧 `answer/citations/entry_result` 与两类持久草稿组织类型、控制器和界面，导致正式回答退化成扁平文本，且大量不可达写逻辑继续占据运行时模块。

本设计采用用户确定的方案二：保留原生基础设施和一致的交互基线，替换知识对话业务模块，不保留新旧双轨。依据与删改范围来自本 change 规格及 `docs/discussions/移动端知识Agent现状与对齐摸排-2026-09-18.md`，其中“恢复旧 Candidate/Revision 入口”等建议已被本轮产品决定替代。

## Goals / Non-Goals

**Goals:**

- 以正式 dialogue 合同恢复当前 Conversation 的历史、阶段、终态、块和 continuation。
- 用现有原生主题与基础组件展示正式块，并让明确 Entry 列表通过底部只读详情按需读取当前正文。
- 正常冷启动默认空白新对话，同时可靠恢复移动端未发送输入、活动 Run 和结果未知提交。
- 降低历史 Sheet 首次展示成本，并以纯原生 Markdown 提升回答与知识正文可读性和可复制性。
- 从移动运行时代码中删除旧 Candidate Draft、Entry Revision、citations、旧 Entry Result 和未生效模式业务。
- 保留登录、Bearer、安全存储、会话/消息分页、范围、消息幂等、前台轮询、取消、前后台及重启恢复。

**Non-Goals:**

- 不修改共享 loop、提示词、预算、模型、工具、Candidate/Revision 服务或数据库。
- 不增加写操作、Operation Review、能力感知、第二套记忆或客户端关键词路由。
- 不实现移动收集、待处理、知识主页面，不迁移或删除测试数据。
- 不重设计 App 壳层，不做依赖大版本升级，不用模拟器或真机替代用户验收。

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

本决定替代此前“原位展开正文”。知识列表按服务端原序保留序号，以标题为主，项目与目录归属独立紧凑展示；列表不显示正文 `summary/excerpt`，关联性质与 `relevance_reason` 独立表达，不把相关理由改写成知识总结。只有 list 语义为 entries 且列表项带数值 `entry_id` 时可打开详情，项目和目录项不可误接 Entry API。

点击可读项后才挂载详情查询，沿用现有 TanStack Query key 与 `getEntryCurrent`。详情的透明 Modal 本身不使用 `slide`，而是由淡入淡出的遮罩和独立上下移动的底部面板组成；关闭动画结束前 Modal 保持拦截背景点击，系统启用减少动态效果时直接切换。其他 Sheet 保持既有淡入语义，共享容器移除没有拖拽行为的横条。详情负责加载、失败重试、当前不可访问、标题、当前正文、弱化的更新时间和关联来源；不再重复“当前知识内容”或固定免责声明。正文使用正常阅读字号与行距，长内容在 Sheet 内滚动，关闭、遮罩和系统返回都只关闭详情并保留主对话滚动位置。

详情以正式知识标识、标题、归属、更新时间、正文和“关联来源”表达当前 Entry；Entry block 仍表达“本轮读取的知识正文”，Evidence block 仍表达本轮核验材料。打开详情只触发单个 Entry GET，不提交消息、不调用模型、不注入 Agent 上下文，也不恢复旧引用、修订或候选保存流程。

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

### 12. 启动恢复由根级移动会话状态区分冷启动与栏目往返

根布局内增加知识对话专用的客户端会话 Provider，其生命周期覆盖底部栏目切换和弹层开关，但在真正的 App 进程启动时重新建立。Provider 保存当前会话选择、空白新对话范围、未发送输入和待确认提交，使短暂切后台、栏目往返或对话页普通重挂载不会被误判为冷启动。

持久工作记录按 `user_id + workspace_id` 生成隔离键，只保存版本、Conversation/Run 引用、最后有效范围、未发送输入、pending submission 的原 `client_message_id`/正文/上下文/目标 Conversation、提交阶段和更新时间。长文本使用 SecureStore 分片，避免把第二份完整消息历史或 Agent 快照持久化。退出登录清理当前身份记录；切换身份或 Workspace 使用不同键，旧身份记录不会被读取。

恢复顺序是：读取本身份记录 → 请求现有会话摘要 → 以现有 Conversation/Message/Run API 复验 → 恢复未发送输入、活动 Run、离开期间刚完成但尚未查看的 Run，或结果未知提交。没有记录时进入保留上次有效范围的空白新对话，首次发送才创建服务端 Conversation。恢复读取或服务端复验失败保持明确错误与重试/退出入口，不能降级为“没有待恢复工作”。

提交前先持久化稳定消息键。若已有 Conversation 的提交响应未知，恢复后先在消息页按 `client_message_id` 对账：已存在则不重发，不存在才允许复用原键重试。若新建 Conversation 的响应本身未知，由于现有创建接口没有幂等键，客户端明确提示该步骤无法安全自动恢复，只允许退出到新对话，不自动再创建；这接受可能遗留一个空 Conversation，但避免重复会话和错误绑定。

正常会话浏览不写成“待恢复工作”；活动 Run 已在前台展示完成、结果未知已对账完成或未发送输入清空后，删除工作记录，仅保留隔离的最后有效范围。因此下一次正常冷启动进入空白新对话，而当前进程内仍保留用户正在看的会话和阅读位置。

### 13. 历史 Sheet 虚拟化且不阻塞新建

历史摘要仍在控制器进入页面时通过既有全量接口请求，不把点击历史误认为网络请求起点。历史入口局部管理 Sheet 开关，避免仅开关弹层导致消息树无关重渲染；列表使用原生 `FlatList`，限制首批和批次渲染量，不嵌套在同方向 ScrollView。新建入口作为固定顶部内容先于列表状态渲染，即使摘要首次加载或失败也可使用；已有数据刷新时保留列表，不用空白 loading 替换。

本轮不增加服务端分页，因此虚拟化只降低 React Native 首屏挂载与更新成本，不减少接口响应体、JSON 解析或内存中的摘要数量。若真机测量显示瓶颈位于网络/解析，需要后续独立后端分页合同，不能在客户端结论中掩盖。

### 14. Markdown 是纯移动展示层

新增 `react-native-markdown-renderer`。该实现使用原生组件和 CommonMark/markdown-it，不使用 WebView；当前版本要求 React 18+、React Native 0.73+，与本工程 React 19 / React Native 0.86 相容。回答 text、candidate 文本、Entry block 正文、Evidence 文本及当前 Entry 正文使用统一的轻量样式，标题限制为移动端正文层级，代码和表格放入横向滚动容器，普通文本保持原样。

Markdown 默认关闭原始 HTML；图片不加载；链接仅允许 `https:`、`http:` 和 `mailto:`，其他协议不执行。文本规则使用原生 `selectable`，不新增复制菜单。结构化 list/statistic/entry/evidence/candidate 的外层语义、顺序和状态不变，不把 blocks 序列化为 Markdown，也不补写无换行的自然语言编号。组件按原文本 memo 化，轮询或弹层开关不会为未变化文本重复解析。

## Risks / Trade-offs

- [旧测试 Run 没有 blocks 时信息减少] → 只保留扁平文本回退；移动端尚未上线，接受不恢复旧复杂交互。
- [公开 list item 为弱类型字典] → 仅使用经类型守卫确认的字段，未知对象只读展示或占位，绝不据此发起写操作。
- [Entry 当前内容与历史块不同] → 底部详情以当前 GET 的知识标题、更新时间和正文为主体，不再增加重复的“当前知识内容”标题；历史 Entry 块继续标明本轮读取语义，两者不相互覆盖。
- [Sheet 切换为滑入影响其他弹层] → 只给 Entry 详情传入局部动画类型，通用 Sheet 默认仍为 fade；减少动态效果时详情使用 none。
- [初始定位与历史阅读竞争] → 以会话键只执行一次，并沿用加载旧页的高度锚点；前后台恢复和关闭详情不重置定位键。
- [旧 operation Run 仍出现在消息页 runs] → UI 不渲染其草稿或写回执；普通正式回答 Run 的恢复不受影响。
- [真实 continuation 不易稳定触发] → 用确定性控制器/组件测试覆盖，真实调用记录为未自然覆盖，不反复消耗模型制造失败。
- [创建 Conversation 响应未知无法可靠找回] → 不自动重试无幂等创建；明确提示并允许退出，已有 Conversation 的消息提交继续按稳定消息键对账和恢复。
- [SecureStore 不适合大对象且原生 key 字符受限] → 仅持久化最小工作记录并对输入/消息正文分片；manifest 与 chunk key 只使用字母数字、`.`、`-`、`_`，测试 mock 执行同等校验；读取、写入和清理失败均显式处理，退出恢复即使清理失败也不得锁死页面，不把本地记录作为正式消息源。
- [历史接口仍返回全量摘要] → FlatList 只减少首屏挂载；网络体积和 JSON 解析限制写入交付记录，不宣称已解决后端分页问题。
- [Markdown 扩大富文本输入面] → 禁用 HTML 和图片，限制链接协议，结构化块边界不变；表格与代码只做横向阅读回退。

## Migration Plan

1. 先提交完整 OpenSpec 工件并通过全库严格校验。
2. 新增正式 block 类型、渲染和 Entry 按需读取；改造阶段/终态与 continuation。
3. 收敛提交设置与线程状态，删除 Candidate/Revision/citation/旧 Entry Result 业务及专用测试。
4. 增加启动工作记录、历史虚拟化、Sheet 分层动画和移动 Markdown，更新产品端侧专题、移动测试与本地讨论交付记录。
5. 运行移动端相关测试、typecheck、lint、OpenSpec 严格校验和 `git diff --check`；在已有服务和凭据可用时做少量真实正式链路检查，不启动或重启服务。
6. 本地提交后等待用户设备验收；未验收前不归档、不推送、不合并。

回滚使用 Git 恢复本 change 的移动端提交；不涉及数据库迁移或业务数据回滚。

## Open Questions

无阻塞产品问题。Evidence 若未来需要独立 Source 快照详情，必须另行决定 typed 后端字段与交互范围，不在本 change 内预留双轨。
