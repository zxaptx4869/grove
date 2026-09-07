## Context

现有统一循环通过 `KNOWLEDGE_AGENT_READ_TOOL_REGISTRY`、`RunToolContext` 与 `dispatch_read_tool` 访问正式 Entry，并由实验层保存结果句柄和精简历史。Project/Node 目录树当前由项目 API 直接读取，Node 以 `parent_id` 表示层级、`position` 表示同级顺序；循环没有目录工具。现有结果块虽然从句柄取真实数值和对象，显示标题仍由模型提供，因此 `main_type` 分组可能被错误命名为一级目录。

本 change 只扩展统一循环原型及实验工作台。正式 Knowledge Agent 路由、公开 API、数据库结构和目录写入能力不变；两个既有活动 change 不归档。

## Goals / Non-Goals

**Goals:**

- 复用真实 Project/Node 模型与产品目录顺序，提供根级和直接子级只读查询。
- 在共享 dispatcher 内落实 Workspace 成员、项目和父节点归属校验，并继承审计与资源控制。
- 用目录专用结果句柄支持跨轮按实际顺序指代。
- 让程序而非模型决定统计、Entry 列表和目录列表的领域标题、范围、维度与数量语义。
- 用真实 SQLite 数据与 FunctionModel 覆盖边界，不发真实模型请求。

**Non-Goals:**

沿用 proposal 所列非目标；尤其不增加目录写工具、独立意图/规划/覆盖模型，不提高预算，不接入旧 Agent 正式流程，不重放历史会话。

## Decisions

### 1. 共享只读 registry 增加 `list_project_directories` v1

工具参数只包含项目引用和可选 `parent_node_id`，Workspace 与 owner 始终由 `RunToolContext` 注入。处理器先核对 WorkspaceMember，再在该 Workspace 内解析项目；父节点查询必须同时满足项目 ID。它一次加载项目节点以构造父路径，再只返回目标父级的直接子节点，排序为 `position, id`，使 position 相同时仍确定性稳定。

根节点 `parent_id IS NULL` 就是项目一级目录，不另造虚拟根节点。查询不连接 Entry，因此空目录天然保留，子孙不会进入直接子级计数。当前实现不分页，`total_count == returned_count`、`has_more=false`、完整性 complete；合同仍显式保留两个计数，避免未来分页混淆。

备选是在实验包中直接 SQL 查询 Node，但这会复制权限、审计和目录语义，无法被共享边界测试覆盖，因此不采用。公开项目树 API 保持响应合同，只复用同级稳定排序辅助函数，避免创建第二套目录数据。

### 2. 对话表面工具支持项目名称或项目 ID，并由目录句柄解析父节点

自然首问可以用唯一项目名；`list_projects` 同时返回真实项目 ID，名称歧义时模型可以要求用户选择或用 ID。目录工具的首次调用不带父节点，追问则优先携带上一轮 `directory_result_handle + position`。实验层验证句柄属于本会话且结果类型为目录，再解析 Node ID；共享处理器仍重新验证 Node 当前归属，历史不成为授权。

目录结果使用独立的 `directories` 记录类型与 `directory_list` 输出块，Entry 的 `open_list_item` 继续只接受 Entry 列表。这样即使两个列表都有“第二项”，也无法交叉解析。历史摘要只保存项目/父节点、节点 ID/名称/路径/顺序、数量、状态和完整性。

### 3. ResultRecord 保存权威 `semantics`，渲染器忽略模型自定义标题

实验适配层根据实际工具、执行参数和返回 payload 构造结构化语义：`subject`（entries/directories）、可信项目范围、筛选、`group_by`、总数/返回数、完整性及中文显示名。模型输出块仍只负责顺序和解释；兼容保留的 `label` 字段不再决定结构化标题。

确定性标题示例为“房子装修 · 一级目录”“全部项目 · 按知识类型统计”“房子装修 · 正式记录列表”。`main_type` 桶由固定映射显示为知识/方法/参数/提醒；`info_nature` 和其他合法维度也使用应用映射。原始 key 继续保留用于诊断。

这种做法不要求改变正式 API schema，也不把结果形态退回二选一。工作台只扩展现有块视图并显示总数、返回数和完整性。

### 4. 继续使用同一预算、事务锁和失败恢复

目录调用走 `_dispatch`，所以在派发前预留现有工具动作预算，并使用 `ReadToolBudget`、取消检查、字节限制、审计记录与 `LoopState.database_lock`。非法历史句柄在表面工具处以 denied 记录且不触碰数据库；共享处理器的访问/归属问题返回明确状态与错误码。任何意外异常仍由 dispatcher 归一为 error，工作台沿用第一批终态保存和下一轮恢复。

## Risks / Trade-offs

- [项目名允许重复，直接按名查询可能歧义] → 返回明确歧义错误；`list_projects` 暴露真实 ID，目录工具接受 ID 作为无歧义引用。
- [现有 Node.position 可能并列] → 在不改变产品 position 语义的前提下用 Node.id 作稳定回退；项目树 API 同步采用相同辅助排序。
- [模型仍可能在自由文字中口误] → 结构化块标题、维度、数值和对象由程序固定；自然语言真伪仍属于人工语义验收，不新增覆盖模型。
- [共享 registry 暴露新工具但正式流程未接线] → registry 只提供白名单执行能力，正式 planner/runner 不会自行发现未注册到其计划合同的工具；测试覆盖既有调用方。

## Migration Plan

无数据库迁移。先完成共享目录查询与测试并提交，再完成统一循环/工作台接线与回归并提交，最后记录自动化验证。回滚可恢复这些代码提交；实验历史仍按既有设计只读保留，新会话使用新合同。人工验收前不归档、不推送、不合并。

## Open Questions

无阻断问题。真实模型是否总能在自然表达下选择正确目录工具留给本次人工验收；无模型测试只证明工具事实、边界和接线。
