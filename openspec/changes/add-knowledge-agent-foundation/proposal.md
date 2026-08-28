## Why

现有 Reader 虽然具备混合召回、带引用回答与 Workspace 隔离，但每次请求只处理当前一句问题，消息仅保存在前端，引用原文也没有经过真实 Source 内容校验，无法作为移动端与 Web 共用的连续知识 Agent 基础。移动端基础工程已经完成，现在需要先建立持久化、可恢复、证据可信的只读 Agent 纵向底座，再逐步增加连续追问和自主调查。

## What Changes

- 新增 Workspace 内持久化的知识对话、消息、范围事件与 Agent Run；每个 Run 固化生成时的 Workspace/项目范围、状态、模型调用与降级摘要，并支持幂等提交、恢复查询、单会话串行和取消。
- 新增三个受范围约束的只读知识工具：搜索正式知识、读取完整 Entry、读取真实 Source/Attachment 证据；模型不能自行传入 Workspace，也不能读取未由当前范围、用户引用或本轮搜索发现的对象。
- 新增 Run Evidence：把本轮实际读取的 Entry、Source、Attachment、原文片段与内容指纹保存为可验证证据句柄；最终引用只能选择这些句柄，不能由模型自由生成 quote。
- 将现有一次性 Reader 生成器收缩为回答组织器，在新 Agent Run 中完成可信的首次问答；回答显式表达知识不足、来源冲突、部分失败和各 AI 阶段降级。
- **BREAKING（产品范围）**：知识 Agent 的用户可选范围改为当前 Workspace「全部知识」或具体项目，不再提供目录节点级范围；目录路径仅作为检索线索和知识归属信息。旧 Reader 页面与兼容 API 的移除留到 Web 接入 change。
- 更新 Agent 与 AI 阅读权威专题，使产品定义与新的范围、会话、Run、证据边界一致。

### Non-Goals

- 不实现追问关系判断、指代解析、工作集版本或连续对话上下文复用。
- 不实现模型自主制定调查计划、多轮改写查询、主动寻找反例或最多三轮的受限研究循环。
- 不接入移动端或 Web 对话界面，不在本 change 移除现有 Web Reader 入口。
- 不提供新增、修改、移动、删除、合并知识或保存回答为 Candidate 的 Agent 工具；既有回答转候选能力保持不变。
- 不联网搜索、不接入 Discovery Agent，不引入多 Agent 协商、独立任务队列或外部消息基础设施。
- 不建设离线知识库、推送通知、流式文本传输或 App 发布能力；客户端先通过持久化 Run 状态恢复和轮询接入。

## Capabilities

### New Capabilities

- `knowledge-agent-conversation`: Workspace 内知识对话、消息、范围事件、幂等提交、历史读取与当前范围管理。
- `knowledge-agent-run`: 一次只读问答的持久化 Run、状态转换、单会话并发约束、取消、恢复和分阶段 AI 可观测性。
- `knowledge-agent-read-tools`: 受可信范围与已发现对象集合约束的搜索、Entry 读取、Source 证据读取及 Run Evidence 契约。

### Modified Capabilities

- `reader-qa`: 从节点/项目范围的一次性 Reader 请求改为 Workspace/项目范围、由持久化 Agent Run 生成的首次问答；引用必须来自服务端核验的真实 Evidence，且检索、重排和回答阶段的降级均可识别。

## Impact

- 后端新增知识对话、消息、范围事件、Agent Run、工具调用、模型调用与 Run Evidence 模型、迁移、schemas、服务、Worker 和 API。
- 复用现有 Session/Workspace 鉴权、混合检索、Entry/Source 数据、Project Context、PydanticAI Provider 与进程内 Worker 模式；不新增外部服务依赖。
- 调整现有 Reader Agent/服务的职责与引用校验，但保留旧 Web Reader 和回答转候选兼容链路，待后续 change 迁移。
- 更新 `docs/产品蓝图/Agent架构与AI边界.md`、`docs/产品蓝图/目录与知识空间.md` 以及 `reader-qa` 主规格。
- 后续移动端与 Web 将共用本 change 的对话与 Run API；本 change 只通过 API、测试和运行记录验收，不实现正式客户端界面。
