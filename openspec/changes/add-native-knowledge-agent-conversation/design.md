## Context

Grove 已完成两块彼此独立但尚未连接的能力：

- 后端 Knowledge Agent 已支持 Workspace/项目范围、持久化对话、连续追问、版本化工作集、quick/auto/investigate、最多三轮调查、Run 轮询/取消/恢复和本 Run Evidence；
- `mobile/` 已是可运行的 Expo Router 原生工程，具备 Bearer Session、真实 Workspace/项目、SecureStore、TanStack Query、四栏导航、安全区和键盘避让，但对话输入仍禁用。

移动原型已经验证「对话为首页、顶栏范围、历史页、过程卡、回答卡、引用 Sheet、连续追问」的产品形态，同时也演示了尚未实现的收集、知识写入、差异确认和撤销。本 change 只把只读对话路径接真实 API，不把原型静态数据或未来写操作带入正式 App。

实施前独立复核 `add-knowledge-agent-bounded-investigation` 发现两个非破坏性契约缺口：Entry 预算在轮末判断，单轮可能先超限；Query 结果 JSON 使用轮内累计值而非自身增量。它们会让移动端显示的调查计数失真，因此先在本 change 前置修复。生产测试 Run 42～46 还显示默认 12 条 Evidence 被首条查询顺序性耗尽、重复 Source/quote 重复计费，且预核验证据远多于最终引用；本次必须优化分配，而不是仅提高数字预算。

## Goals / Non-Goals

**Goals:**

- 在原生 App 跑通创建/恢复对话、历史分页、范围切换、连续提问和回答模式覆盖。
- 将服务端异步 Run 映射为可取消、可恢复、前后台安全的移动状态机。
- 以原生卡片和 Bottom Sheet 呈现回答、来源原文、冲突、知识不足、调查摘要与降级。
- 为历史页提供最近消息与关联 Run 的一次性水合，避免逐消息 N+1。
- 补齐 Workspace 引用项目归属和冲突双方 Evidence 的 API 契约。
- 严格执行 Entry 预算，并让逐 Query 审计计数准确。
- 在硬预算内让多查询、不同维度和冲突双方公平竞争，并仅为全局会采用的候选读取 Evidence。
- 以最终实际采用的 Evidence 重建 coverage、gaps 与冲突摘要，统一后端回答状态和正文职责。
- 对齐已确认移动原型的结构、密度、键盘和三个目标视口。

**Non-Goals:**

- 不接入 Web Reader，也不修改桌面信息架构。
- 不实现任何知识写入、Candidate、差异确认、撤销、收集或知识浏览。
- 不实现流式 token、WebSocket、推送、离线回答或移动后台任务。
- 不实现对话重命名/删除/搜索/置顶、工作集单项管理或开发者观测面板。
- 不接相机、语音、附件、系统分享，不渲染任意 Markdown/HTML。
- 不引入 CopilotKit、WebView 或共享 Web 组件。

## Decisions

### 1. 原生端只消费统一 Knowledge Agent API

在 `mobile/src/knowledge-agent/` 建立独立的 TypeScript 类型、API、Query hooks 和展示适配器，Bearer Token 继续通过现有 `request()` 注入。App 不调用旧 `/reader/ask`，也不在客户端复制检索、上下文判断或调查规则。

页面 `app/(tabs)/index.tsx` 只承担路由与页面组合，消息、Run、模式和范围状态拆到 hook/组件中，避免继续扩张当前单文件占位实现。新增 `expo-crypto` 生成 `client_message_id`，使用 `@testing-library/react-native` 验证组件交互。

未引入 CopilotKit：当前协议已经稳定，原生端仍需自定义卡片、Sheet、安全区和 AppState 恢复；通用 Web 对话库收益不足且会引入第二套运行时抽象。

### 2. 对话在首次发送时懒创建

App 启动后读取按最近活动排序的对话：存在时默认恢复最近一条；不存在或用户点「新对话」时进入本地 draft conversation。用户可以先选「全部知识」或项目，首次发送时按该范围创建服务端 Conversation，再提交消息。

这样不会因为用户多次点「新对话」产生大量空记录。创建成功但提交失败时，客户端保留 conversation_id、消息文本和同一个 `client_message_id`，网络重试不得再建对话或换幂等键。收到确定的 201/200 后才清除 pending submission。

历史 Sheet 显示标题、范围、最近活动、活动主题和最新 Run 状态；支持选择既有对话和新建，不在本 change 增加重命名、删除或搜索。

### 3. 历史 API 返回最近页和规范化 Run 集合

`GET /conversations/{id}/messages` 调整为：无 cursor 时选择最近 N 条，响应内仍按时间正序排列；`next_cursor` 指向更早消息，客户端上拉时把更早页去重后 prepend。Cursor 使用服务端不透明 `before` 语义，旧方向没有正式客户端依赖。

`KnowledgeMessagePageOut` 增加 `runs: KnowledgeRunOut[]`，包含当前页消息关联的去重 Run；消息继续只保存 `run_id`，客户端按 ID 关联。这样历史回答一次请求即可获得结构化 answer、引用、状态、fallback 和调查摘要，不把相同 Run 深度嵌入用户/助手两条消息。

`KnowledgeConversationOut` 增加最近 Run 的 id/status/current_step/updated_at 摘要。列表服务批量查询每个对话最新 Run，不能制造 N+1。App 进入对话后仍以 Run 详情为最终状态来源。

未选择让客户端为每个历史 run_id 并发 GET，因为长对话会造成请求风暴、部分失败难以重建稳定消息列表。

### 4. 范围属于 Conversation，不属于全局 App 偏好

草稿对话的范围是本地创建参数；服务端对话创建后，顶栏范围来自 Conversation。切换已有对话范围调用 PATCH，成功后 refetch conversation/messages；同范围选择在客户端和服务端均为 no-op，不创建 `scope_change`。

活动 Run 时范围选择禁用，或 PATCH 返回 409 后展示「正在回答，完成或取消后再切换」。历史回答卡底部使用其 Run 范围快照；Workspace 回答的引用显示各自项目归属。范围切换事件作为居中分隔条，不包装成助手回答。

### 5. 上下文与回答方式是下一条消息的一次性覆盖

默认提交 `context_mode=auto`、`answer_mode=auto`。输入区提供低频设置 Sheet：

- 理解方式：自动、继续当前主题、新话题；
- 回答方式：自动、快速回答、深度查找。

只有非默认值时在输入区上方显示可移除 chip；成功提交后恢复 auto，避免后续消息意外沿用高成本或强制语义。对话头部显示活动主题标签和 Entry 数，但首版不展开工作集条目、不支持单项移除。用户也可通过「新对话」明确切断旧上下文。

模式选择是相对原型新增的必要交互，因为受限调查 API 在原型确认后落地；它保持低频，不改变对话首屏主任务。

### 6. Run 采用前台轮询和服务端恢复

提交返回 waiting Run 后，TanStack Query 在 AppState 为 active 时轮询 `GET /runs/{id}`：waiting/processing 保持轮询，终态停止；进入后台即停，恢复 active、重新登录或重新打开对话时立即 refetch。移动端不保持后台定时器，也不把本地缓存当权威状态。

`current_step` 映射为有限的用户文案：准备、理解问题、选择回答方式、检索正式知识、读取 Entry、核验证据、深度查找第 N 轮、综合回答。只显示可验证阶段，不显示 controller reason 或隐藏推理。活动卡提供取消；取消请求后显示「正在取消」，直到服务端终态。

网络超时分两类：

- 提交结果未知：保留同一幂等键重试；
- Run 轮询失败：保留服务端已知 Run 卡和手动重试，不重新提交问题。

终态 failed 的「重新提问」创建新 `client_message_id` 和新 Run；它不是网络幂等重试。409 时 refetch 对话最近 Run，而不是本地制造第二个活动任务。

### 7. 回答状态以结构化 answer 为准

Run 的 `completed/partial/failed` 描述执行完成度，回答卡主要依据 `answer.status`：

- completed：正常带引用回答；
- partial：保留有效部分，并显示部分结果/降级说明；
- insufficient：明确知识不足和 gaps，不因 quick Run 是 completed 而显示成功语气；
- failed：保留可用信息但显示模型或工具不可用及重试；
- clarification：展示澄清卡，用户在同一对话自然回复。

investigation summary 以「深度查找 · N 轮 / M 次查询」和停止原因呈现，可展开 coverage/gaps/conflicts；不展示完整 Query 账本。fallback summary 转换为面向用户的短说明，不默认展示 provider/model/error 原文。

### 8. 引用与冲突返回可直接展示的快照

`KnowledgeRunCitationOut` 增加 Evidence 已有的 `project_id`、`project_name`、`node_path` 快照。`KnowledgeConflictOut` 保留现有兼容字段并增加完整 `citation_a` / `citation_b`，两侧都含 Source、quote 和归属，避免客户端拿 evidence_id 猜对象或再次读取已变化来源。

回答卡把 citations 放在正文下方的来源条，不伪造段落级内联锚点——当前 API 没有答案 span 到 Evidence 的映射。点击后打开 Bottom Sheet，依次显示「对应 Entry」、项目/目录、「本次回答核验的 Source 原文」和 Source 标题；明确这是 Run 快照。可提供「查看当前知识」跳转/读取现有 Entry，但当前 Entry 与历史快照必须分区标注。

这是相对原型内联引用的有意偏离：先保证引用关系真实可解释，未来若后端提供 answer span 再做精确内联标记。

### 9. 调查预算和 Query 审计在客户端接入前硬化

每轮读取搜索结果前计算 `remaining_entries`，只允许至多该数量的新 Entry 进入 read/Evidence/账本；达到零立即停止，不得让单轮批量结果越过快照上限。测试必须断言 Investigation、Round 和账本实际计数均 `<= max_entries`，而不只断言停止原因。

`_execute_query_round` 为每条 Query 单独维护 hits/new_entries/entries_added/evidence_added/denied/unavailable 局部计数，Round 再累加；Query JSON 不再写前序查询累计数。这只修正审计数据，无数据库迁移。

### 10. 视觉基线与原型偏离

采用 `grove-mobile-agent-prototype.html` 的结构：四栏壳、对话默认页、居中范围按钮、右侧历史、滚动 thread、底部 composer、过程/回答卡、范围与引用 Bottom Sheet；沿用 `mobile/src/theme.ts`、安全区和原创 `NavIcon`，正式代码全部使用 React Native 组件。

主验收视口 390×844，扩展 360×800 与 412×915。固定顶栏、composer、系统键盘和底栏不得互相遮挡；输入聚焦时沿用 `tabBarHideOnKeyboard`，长回答、历史和 Sheet 独立可滚动。

有意偏离原型：

- 使用真实系统键盘，不实现原型键盘模拟；
- 只保留只读提问、追问、来源、冲突和不足，删除写入/合并/差异/撤销及其他三栏静态业务记录；
- 过程卡严格映射服务端 current_step，不播放伪造步骤动画；
- 引用先使用可验证来源条 + Sheet，不伪造正文 span；
- 新增低频模式 Sheet 和真实 loading/empty/error/retry/cancel 状态；
- 建议问题不显示静态知识数量或保证答案，只作为可编辑的输入示例。

#### 视觉基线（来自原型 CSS，主视口 390×844）

- 全局令牌：页面背景 `#F7F8F7`、表面 `#FFFFFF`、柔和表面 `#F1F4F2`、边框 `#DDE3DF`；正文 `#17201C`、次要 `#66716B`；品牌绿 `#236748` / 浅绿 `#E8F3ED`；AI 紫 `#7251A5` / 浅紫 `#F2EDF8`；已确认青 `#187C72` / 浅青 `#E7F5F2`；风险琥珀 `#9A6419` / 浅琥珀 `#FFF5DF`；错误红 `#B43C3C` / 浅红 `#FCEDED`；遮罩 `rgb(15 24 19 / 36%)`。
- 字体：系统字体栈（含 PingFang SC）；正文 14/21；顶栏范围 15/21（字重 700）；页面标题 23/31（字重 700、字距 -0.5）；说明 13/21、11/17、10/16 分级；卡片标题 16/23（字重 700）。
- 应用壳：顶栏最小高 58 + 安全区，三列 44 / 弹性 / 44，底部 1px 边框；底栏高 66 + 安全区，四列平分，图标 24、描边 1.8。
- 页面边界：thread 水平留白 16，顶部 18，底部 154（给 composer 与底栏留空）；intro 顶部留白 44。
- 固定组件：卡片 10 圆角 + 1px 边框 + 轻阴影；来源 chip 最小高 40、7 圆角；composer 50 高、13 圆角、输入高 40（最大 96）；发送按钮 40×40、9 圆角；用户气泡最大宽 84%、绿底白字；Sheet 顶部 18 圆角、最大高 84%、手柄 36×4；触控目标 ≥44。
- 状态语义：进行中/neutral、已取消/neutral、正常回答/confirmed、知识不足/risk、失败/error、AI 建议/ai，均以文字 + 颜色表达。

#### 有意偏离与平台差异补充

- React Native 的 `TextStyle.fontWeight` 只接受 100–900 标准字重：原型中的 430/650/680/720/750 统一映射为 400/600/700，视觉层级关系保持不变，作为平台渲染差异记录。
- 引用 Sheet 的「查看当前知识」在本 change 只读范围内不接 Entry 浏览，按钮固定为禁用并明确说明「暂不可用」，避免伪造当前对象入口；历史快照与当前知识分区标注保留。
- 历史时间使用相对时间（刚刚 / N 分钟前 / N 小时前 / 昨天 / N 天前），不伪造原型中的静态时刻。
- 建议问题只作为可编辑输入示例（点击填入输入框），不承诺答案或展示静态知识数量。

### 11. 先汇总候选，再确定性分配 Evidence 硬预算

每个调查轮先执行尚未重复的合法搜索，将其结果连同 Query、Entry、Source 与可读取 quote 形成候选池；在池完成前不按搜索返回顺序读取并消耗 Evidence。随后服务端以稳定排序执行全局选择：先给每个有可接纳候选的查询保留一个名额，再轮转补足；同一 Entry、同一来源和等价规范化 quote 合并为一个候选成本，但保留所有可追溯关联。存在真实相反主张时，冲突两侧在不同 Entry/Source 下可各保留一个名额，不能被普通重复消重误删。

全局选择在每步同时检查剩余 Evidence/Entry、单 Query、单 Entry、重复 Source 的配额；若候选已无法产生新的可接纳 Entry 或 Evidence，立即停止其后续读取步骤。Round 与 Query 审计分别保存搜索命中、候选、被分配、去重/限额拒绝和实际新增值，使恢复从持久化账本重建同一选择结果。服务端预算仍为最终硬边界，所有查询和对象仍由 Run 固化 Workspace/项目范围过滤，且该算法只读正式 Entry 与 Source，不写正式知识。

默认 Evidence 预算在实现前保持 12；实现后以 Run 42～46 的同类真实数据和回归测试评估引用有效利用率、维度覆盖与缺口。只有在分配已消除明显浪费且 12 条仍稳定不足以支撑核心结论时，才适度上调并把测量结论写入验证记录；不得以提高默认值掩盖重复分配。

未选择“逐查询固定均分”：部分查询可能没有可核验证据，固定切片会浪费预算。也未选择边搜索边贪心读取：它会重现首条返回先占满预算的问题。

### 12. 后端以最终 Evidence 判定回答状态和终态覆盖

`Run.status` 只表达执行生命周期；`answer.status` 由最终组装器权威生成。`completed` 表示核心问题已由充分且有效的当前 Run 引用支持；`partial` 表示有用正文和有效引用存在，但最终 coverage/gaps 或引用校验仍显示影响完整性的明确缺口；`insufficient` 表示没有足以组成有用回答的证据，或核心问题基本无法回答。预算、轮次或 `stop_reason` 只解释停止原因，不能直接把有有效核心回答降为 `insufficient`；“没有穷尽知识”也不是不足。

控制器在搜索前提出的 coverage/gaps 只作为过程计划。最终阶段从实际有效 citation、采用 Evidence、可核验冲突与未满足的核心维度重新计算正式 coverage/gaps/conflicts；过程摘要不作为事实，任何事实结论都必须能回到当前 Run Evidence。部分失效引用先剔除，再用剩余有效引用与缺口判定状态。

### 13. 正文和结构化卡片各司其职

回答 prompt 以问题类型约束首句：决策先给推荐、对比先给主要差异、操作直接给步骤、事实直接给答案。禁止复述问题或以“关于这个问题”“根据当前已确认知识”“以下是基于正式知识”等无信息开场；只有多维长回答才可先给一至两句实际信息的结论摘要。范围、来源数量、部分结果、预算、轮数、停止原因与 coverage/gaps 不进入正文，分别由回答卡与调查摘要呈现。此规则由 prompt、结构化输出责任和测试共同保证，不在前端做字符串删除。

### 14. 原生端状态、Sheet 与恢复入口

原生端只显示后端 `answer.status`，删除 `insufficient → partial` 的本地重分类。首次轮询若直接返回终态，状态归并必须清空 `activeRun`；取消失败作为持久错误留在 Run 卡并允许原取消重试；`partial`、可恢复 fallback、failed 与 cancelled 均提供上下文适配的重新提问/重试入口。History、Scope、Mode、Citation Sheet 使用独立滚动容器，关闭后恢复对话状态。draft 项目范围在本地状态中同时保存 `projectId` 与 `projectName`，不能退化为泛化“项目”。

### 15. 每个平台只有一个键盘避让负责人

Android 使用 `softwareKeyboardLayoutMode=resize`，由系统调整可用高度；Composer 不再加完整 `keyboardHeight` padding，也不以额外 LayoutAnimation 掩盖重复布局。iOS 由 `KeyboardAvoidingView`（padding）和安全区负责，底栏在键盘可见时隐藏；ScrollView 的底部空白根据 Composer、Safe Area、Tab Bar 与当前平台可用高度动态计算，不再固定 154px。多行高度变化、发送、模式切换和键盘开闭共享同一布局来源，保持末条消息与 Composer 可见。

本机缺少原生模拟器时，不把 Web 预览视为验收；实现后仅记录未验证项，保留 iOS/Android 模拟器或真机对 390×844、360×800、412×915、动态字号及 reduce-motion 的补验责任。

### 16. 调查预算按实际接纳兑现，终态摘要与恢复状态按实体绑定

Source 候选只是读取尝试，不等于已消耗的 Evidence。全局选择维持每 Query、Entry 与来源的公平上限，但只在 `ledger.add_evidence` 成功后计入已接纳数量；不可引用、同 Entry 重复 Source 或等价 quote 被拒绝时，继续从同一稳定候选队列选择替补，直到实际 Evidence 达到硬上限或候选耗尽。这样不突破服务端预算，也不会因首个失效候选让后续有效 Source 永久失去机会。

最终 citations 先按当前 Run Evidence handle 去重；coverage 的数量统计只使用该去重后的集合。模型给出的 coverage/gaps 仅能作为候选摘要：每条最终 coverage/gap 必须关联至少一个最终有效 Evidence handle，或在服务器可验证的“缺失维度”集合中存在；无法关联的模型自由摘要不持久化。模型缺省结构字段时，服务端以实际 citations/Entry 生成最小 coverage，并以账本中可验证的未满足维度生成 gaps，不能默认“完整、无缺口”。

移动端取消错误使用 `{ runId, message }` 绑定，只有活动 Run 的 id 相同才显示；切换会话、建立草稿或提交新 Run 时清理旧错误。partial、fallback、failed 与 cancelled 共用“重新提问”入口，但每次均创建新的 `client_message_id`，不把正常重新提问误作取消或幂等重放。

## Risks / Trade-offs

- [轮询增加请求和电量] → 仅前台活动 Run 轮询，终态/后台立即停止，恢复时一次 refetch；后续有真实压力再评估推送或长连接。
- [消息分页方向改变影响未知调用方] → 当前没有正式客户端消费；保留不透明 cursor，更新后端测试并一次完成移动接入。
- [消息页携带 Run 使响应变大] → 每页最多 30 条、Run 去重且不含 observability/完整账本，显著小于 N+1 成本。
- [回答文本没有引用 span] → 不伪造内联关系，先用来源列表与 Evidence Sheet；未来用独立 change 增加结构化 claim-to-evidence。
- [App 在提交超时后状态不确定] → 同一 conversation/client_message_id 重试；重启后从最近对话和服务端消息恢复。
- [范围切换与活动 Run 冲突] → 客户端预禁用，服务端 409 作为最终防线，并提供取消/等待。
- [真实模型运行时间超过移动会话] → 服务端 Run 持久化，App 前后台不影响执行；历史摘要和 Run GET 恢复。
- [全局候选池延迟 Evidence 读取] → 查询仍受固定预算；只持久化轻量候选元数据并在恢复时重建，读取只发生在已选候选，降低无效 I/O。
- [去重错误掩盖真实冲突] → 只合并相同 Entry 或等价内容的重复候选；不同 Entry/Source 的相反主张保留双边 Evidence 名额。
- [状态判定过严或过松] → 用核心维度、最终有效引用和明确 gaps 的表驱动测试覆盖预算停止、边缘证据、无证据和部分引用失效。
- [iOS/Android 键盘策略分叉] → 各平台仅保留一个布局负责人，并以原生设备矩阵验收，不用动画或 Web 截图掩盖。
- [候选失效使预算虚耗] → 配额只按实际写入的 Evidence 计数；拒绝候选后从稳定队列补位，并用硬预算回归测试保证不超限。
- [模型摘要漏填或夸大覆盖] → coverage/gaps 与最终 citations/可验证缺口建立关联，模型字段仅为候选；去重引用后再统计来源数。
- [移动端错误跨 Run 泄漏] → 取消错误绑定 runId，并在会话/新 Run 边界清理；组件测试覆盖切换和重新提问。
- [原型功能丰富导致用户期待写操作] → 正式 UI 不展示未实现按钮，Non-Goals 与空栏目说明保持明确。
- [citation 新字段与旧数据删除] → 使用 Evidence 创建时快照；已删除对象仍展示快照标题/quote，当前对象跳转不可用时明确说明。

## Migration Plan

1. 先修复 Entry 预算、逐 Query 计数、同范围 no-op 和最近页历史契约，运行全部后端回归。
2. 扩展 citation/conflict 与对话/消息响应字段；均来自现有表，无 Alembic 迁移。
3. 在移动端建立 API/types/hooks 和纯状态测试，再逐步替换对话占位页。
4. 接入历史、范围、提交/轮询/取消、回答与引用，最后按原型做多视口和真实键盘对齐。
5. 后端可先部署；旧客户端忽略新增字段。移动端上线前必须与含新消息分页语义的后端版本绑定。

若需回滚移动端，可恢复占位 Conversation 页面而不影响服务端数据；若回滚后端，必须同时回滚尚未发布的移动包，避免分页方向和 citation 字段不匹配。

## Open Questions

无阻塞实施的问题。对话删除/重命名、工作集单项管理、正文内联引用和 Web 统一入口均保留给真实使用后的独立 change。
