## Why

新项目目前只能手动建目录或看到“与 AI 共创目录”占位弹层，Directory Agent 尚未实现。本 change 让用户从零开始用 AI 起草项目目录：通过问卷式澄清理解需求，生成可视化候选树，用户内联编辑后确认原子应用，把“从空目录开始”从手动负担变成 AI 共创闭环。

## What Changes

- 新增 Directory Draft 数据模型：`directory_drafts`（每项目一份活跃草稿，状态机 `drafting / awaiting_input / pending_confirm / confirmed / discarded`，`next_action` 为 `clarify / generate`）与规范化草稿节点表 `directory_draft_nodes`。
- 新增 `agents/directory.py`：从零起草 + 问卷式澄清。澄清为一次返回 3–5 道结构化问题（每道带选项、支持单选/多选与自由输入），用户一次提交全部答案；必要时最多再补一批（澄清批次上限 2），之后必须生成候选树。无密钥时确定性兜底。
- Agent 输入：项目说明 + Project Context 快照（概要、关注方向、目录主题、知识覆盖）+ 用户答案；AI 输出永远是候选，只进 Draft。
- 新增目录起草 API：创建/读取草稿、提交澄清答案、内联编辑草稿节点（增/删/改名/改说明）、确认应用、丢弃。
- 新增对话调整草稿：候选树生成后开放聊天，用户发消息，Agent 返回回复文字与（可选）更新后的候选树，返回树时自动替换草稿节点；会话轮数上限 30，每次请求把当前会话全部消息喂给模型，不做截断或历史压缩。
- 确认应用：应用层校验（parent 引用、无环、名称长度、节点上限 200、空目录起始）后原子创建正式节点，成功后标记草稿已应用并触发项目上下文刷新。
- 前端：把占位弹层替换为目录共创工作区（问卷澄清 → 候选树 → 对话调整 → 内联编辑 → 应用确认），布局为候选树在左、对话区在右；空目录内容区与知识空间页头两个入口接入真实能力。

## Non-Goals

- 不做节点拓展（对现有节点 AI 细化）→ 留给 `add-directory-agent-node-expansion`。
- 不做结构化增量操作（AddNode / Rename / Move…），对话调整使用全量树回复；不做消息截断与历史压缩。
- 不做思维导图浏览、语义检索。
- 不做流式输出（SSE/WebSocket）。
- 不自动应用草稿；不修改正式 Node 模型；不做跨项目草稿与草稿历史。

## Capabilities

### New Capabilities

- `directory-drafting`: Directory Agent 从零起草目录、问卷式澄清、可视化候选树、内联编辑与确认应用。

### Modified Capabilities

- `node-tree`: 知识空间工作台中的“AI 共创目录”入口由占位提示改为可发起真实目录起草流程。

## Impact

- 后端：新增 Directory Draft 模型与迁移、Directory Agent、起草服务与 API；确认应用复用节点创建逻辑并校验。
- 前端：新增目录共创工作区组件，替换 `ProjectPage` 占位弹层。
- 数据：新增 `directory_drafts`、`directory_draft_nodes` 表；不改变正式 `nodes` 表结构。
- 依赖：无新增第三方依赖。
