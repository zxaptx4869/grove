## Why

知识 Agent 的独立问答、连续追问和受限调查已经在后端形成完整的可恢复协议，原生 App 也已有登录、Workspace/项目范围和四栏壳层，但默认「对话」页仍是不可发送的占位状态。现在需要交付第一条真实移动纵向链路，让用户能在手机上持续提问、查看依据并恢复后台 Run，而不是继续扩展无人使用的后端能力。

## What Changes

- 原生 App 对话首页接入真实知识 Agent：首次发送按当前范围懒创建对话，支持恢复最近对话、新建对话、历史列表和向上加载更早消息。
- 顶栏持续显示 Workspace「全部知识」或具体项目范围；既有对话的范围切换调用服务端并显示范围事件，活动 Run 期间禁止切换并提供等待或取消路径。
- 输入区接入真实键盘、稳定 `client_message_id` 和幂等重试；默认自动理解上下文与自动选择回答方式，并提供低频的「继续当前主题 / 新话题」以及「快速回答 / 深度查找」显式覆盖。
- 用 TanStack Query 管理会话、消息和 Run；前台轮询 waiting/processing Run，进入后台停止轮询，回到前台或重启后从服务端恢复，不依赖移动端持续运行任务。
- 将 waiting、检索、证据核验、调查轮次、综合、取消等服务端步骤映射成用户可验证的过程卡；支持取消活动 Run、网络失败原键重试，以及终态失败后的新 Run 重试。
- 原生展示结构化回答、知识不足、冲突、实际回答模式、调查停止原因与未解决缺口；降级只显示用户能理解的受影响阶段和结果，不暴露隐藏推理。
- 引用以可点击条目呈现并打开原生 Bottom Sheet，明确区分 AI 回答、Entry 标题、Source 原文快照、项目/目录归属；Workspace 范围结果必须显示项目归属，冲突双方都能查看各自 Evidence。
- 扩展对话历史 API：初次请求返回最近一页且按时间正序渲染，游标向前加载更早消息；同页规范化返回关联 Run，避免移动端逐条 N+1 请求；对话摘要返回活动/最近 Run 状态以支持恢复。
- 同范围切换改为幂等 no-op，不产生多余 `scope_change` 消息。
- 硬化上一 change 的两个验收缺口：调查每轮接纳 Entry 时严格受剩余 Entry 预算限制，不得先超额再停止；每条 Query 的结果计数保存自身增量而非轮内累计值。
- 修复真实调查中首条查询垄断 Evidence 的问题：先汇总各查询候选，再以确定性的全局选择、维度覆盖、单项限额与来源/quote 去重分配硬预算；只读取仍可能被接纳的 Evidence，保留恢复、取消、审计及 Workspace/项目隔离边界。
- 统一后端 `completed` / `partial` / `insufficient` 回答语义，基于最终有效引用与实际缺口生成终态 coverage/gaps；回答正文直接回答问题，状态、范围、调查预算与过程信息分别交由结构化区域呈现。
- 修复原生端键盘二次避让、不可滚动的长 Bottom Sheet、draft 项目名称丢失、首次轮询终态未清理活动 Run、取消错误吞没、partial/fallback 缺少恢复入口，以及 Jest `forceExit` 掩盖异步资源泄漏的问题。
- 修复审查确认的回归边界：不可引用或重复 Evidence 候选不得预占并浪费预算；终态 coverage/gaps 必须能回溯到最终有效 Evidence；同一 Evidence 不得在引用或覆盖统计中重复计数；取消错误仅属于发起取消的 Run，且 partial/fallback 必须可重新提问。
- 按现有移动 Agent 原型实现正式原生组件，并记录本次只读能力对原型中未来写操作、静态业务状态与引用布局的有意裁剪。

### Non-Goals

- 不迁移或重做 Web 端旧 Reader/AI 阅读入口；Web 统一对话单独规划。
- 不实现创建、修改、移动、合并、删除 Entry/目录，不实现「整理成知识」、Candidate 确认、差异审阅、执行回执或撤销。
- 不接入收集、待处理或知识栏目真实业务，不实现相机、语音、附件、系统分享或推送。
- 不实现流式 token、WebSocket、离线回答、后台常驻轮询或本地模型；后台执行仍由服务端 Worker 完成。
- 不实现对话重命名、删除、搜索、置顶、跨 Workspace、多账号切换或工作集单项移除。
- 不把 observability/debug 详情、完整调查账本或模型 provider 参数暴露为普通用户界面。
- 不引入 CopilotKit、WebView、Web 组件或第二套领域协议；不直接复制原型内联样式和演示脚本。

## Capabilities

### New Capabilities

- `native-knowledge-agent-conversation`: 原生 App 的真实对话生命周期、历史恢复、范围、输入模式、幂等提交、Run 轮询/取消与前后台恢复。
- `native-knowledge-agent-answer`: 原生过程卡、回答、引用、冲突、知识不足、调查摘要、降级与失败恢复的展示和交互契约。

### Modified Capabilities

- `native-mobile-foundation`: 对话默认页从明确占位升级为真实知识 Agent，同时保持四栏壳层、原生组件、安全区和键盘边界。
- `knowledge-agent-conversation`: 历史分页改为最近页优先并规范化携带关联 Run；对话摘要暴露恢复所需 Run 状态；同范围切换不再产生事件。
- `knowledge-agent-investigation`: Entry 硬预算在接纳每条搜索结果前实施，任何轮次都不得超额。
- `knowledge-agent-investigation-ledger`: 每条查询的审计结果保存该查询自身的命中、新增、不可用与 Evidence 增量。
- `reader-qa`: 引用响应补足项目/目录快照，冲突双方返回各自完整可展示 Evidence；回答状态、终态 coverage/gaps 与正文组织由最终有效 Evidence 权威决定。

## Impact

- `mobile/` 新增知识 Agent API 类型/客户端、Query hooks、会话状态、对话/回答/过程/引用组件及测试依赖；替换对话页占位实现，但不改变其他三栏的未接入状态。
- 后端扩展知识对话、消息页、Run 摘要和回答 citation/conflict schemas 与组装查询；修复同范围切换、Entry/Evidence 分配、逐 Query 计数、回答状态和终态覆盖，无新正式知识写入。
- 更新原生 App 与移动验收说明；视觉基线采用 `docs/prototypes/grove-mobile-agent-prototype.html` 的只读路径，在 `design.md` 记录有意偏离。Android `resize` 仅由系统负责键盘避让，iOS 使用平台原生避让路径，二者均不重复补偿键盘高度。
- 验收覆盖后端回归、移动 Jest/lint/typecheck、Expo 构建、前后台/断网/幂等/取消走查，以及 390×844、360×800、412×915 的安全区、键盘、长回答和 Bottom Sheet。
