## Context

Grove 已完成两块彼此独立但尚未连接的能力：

- 后端 Knowledge Agent 已支持 Workspace/项目范围、持久化对话、连续追问、版本化工作集、quick/auto/investigate、最多三轮调查、Run 轮询/取消/恢复和本 Run Evidence；
- `mobile/` 已是可运行的 Expo Router 原生工程，具备 Bearer Session、真实 Workspace/项目、SecureStore、TanStack Query、四栏导航、安全区和键盘避让，但对话输入仍禁用。

移动原型已经验证「对话为首页、顶栏范围、历史页、过程卡、回答卡、引用 Sheet、连续追问」的产品形态，同时也演示了尚未实现的收集、知识写入、差异确认和撤销。本 change 只把只读对话路径接真实 API，不把原型静态数据或未来写操作带入正式 App。

实施前独立复核 `add-knowledge-agent-bounded-investigation` 发现两个非破坏性契约缺口：Entry 预算在轮末判断，单轮可能先超限；Query 结果 JSON 使用轮内累计值而非自身增量。它们会让移动端显示的调查计数失真，因此先在本 change 前置修复。

## Goals / Non-Goals

**Goals:**

- 在原生 App 跑通创建/恢复对话、历史分页、范围切换、连续提问和回答模式覆盖。
- 将服务端异步 Run 映射为可取消、可恢复、前后台安全的移动状态机。
- 以原生卡片和 Bottom Sheet 呈现回答、来源原文、冲突、知识不足、调查摘要与降级。
- 为历史页提供最近消息与关联 Run 的一次性水合，避免逐消息 N+1。
- 补齐 Workspace 引用项目归属和冲突双方 Evidence 的 API 契约。
- 严格执行 Entry 预算，并让逐 Query 审计计数准确。
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

## Risks / Trade-offs

- [轮询增加请求和电量] → 仅前台活动 Run 轮询，终态/后台立即停止，恢复时一次 refetch；后续有真实压力再评估推送或长连接。
- [消息分页方向改变影响未知调用方] → 当前没有正式客户端消费；保留不透明 cursor，更新后端测试并一次完成移动接入。
- [消息页携带 Run 使响应变大] → 每页最多 30 条、Run 去重且不含 observability/完整账本，显著小于 N+1 成本。
- [回答文本没有引用 span] → 不伪造内联关系，先用来源列表与 Evidence Sheet；未来用独立 change 增加结构化 claim-to-evidence。
- [App 在提交超时后状态不确定] → 同一 conversation/client_message_id 重试；重启后从最近对话和服务端消息恢复。
- [范围切换与活动 Run 冲突] → 客户端预禁用，服务端 409 作为最终防线，并提供取消/等待。
- [真实模型运行时间超过移动会话] → 服务端 Run 持久化，App 前后台不影响执行；历史摘要和 Run GET 恢复。
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
