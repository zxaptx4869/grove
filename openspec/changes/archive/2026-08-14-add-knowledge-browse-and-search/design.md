## Context

确认台已能把候选归档为 `Entry`，知识空间通过 `GET /api/projects/{id}/nodes/{node_id}/entries` 读取某节点的直接 Entry。当前只有一种卡片展示、无列表视图、无直接/后代范围、无搜索；`EntryOut` 证据不含来源标题、不含节点名。本 change 补齐浏览与检索，不改变 Entry 数据模型。

## Goals / Non-Goals

**Goals:**

- 知识空间支持卡片/列表视图切换与按项目记忆偏好。
- 支持「仅本节点 / 仅后代」范围浏览（后代为严格后代，不含本节点）。
- 项目内与全局关键词搜索，覆盖标题、内容、目录与 `Source.title`。
- 来源标题与目录名可展示（Entry 响应补 `source_title` 与 `node_name`）。

**Non-Goals:**

- 排序/筛选/批量管理、语义搜索、FTS、思维导图、Entry 详情页、全局搜索锚定到具体 Entry。

## Decisions

### D1：直接/后代语义与后端递归

采用「排除式」：`直接 = Entry.node_id == 选中节点`；`后代 = 选中节点全部严格后代节点的直接 Entry 并集`，不含选中节点自身。列表接口增加 `scope` 参数（`direct` 默认 / `descendants`）。`descendants` 时后端先沿 `parent_id` 递归收集后代节点 id，再 `Entry.node_id IN (...)` 查询；结果统一按 `created_at DESC`。

理由：用户已确认排除式更清晰，直接数与后代数互斥、无重叠；后端递归集中在服务层，前端只负责传 scope。

### D2：Entry 响应补目录名与来源标题

- `EntryOut` 增加 `node_name`（主目录节点名）。
- `EntryEvidenceOut` 增加 `source_title`（证据指向 Source 的标题）。

读取时对 `Entry` 预加载 `Entry.node` 与 `Entry.evidences → EntrySourceEvidence.source`，避免 N+1。`node_name` 用于列表「目录」列与全局搜索展示；`source_title` 用于卡片/列表/搜索的「来源」展示。

理由：蓝图要求卡片与列表突出「来源」、列表突出「目录」；这两字段是派生字段，不落库、不新增表。

### D3：列表默认倒序

`list_entries_by_node` 由 `created_at ASC` 改为 `created_at DESC`（最新确认在前），直接/后代视图一致。不做交互式排序（P2）。

### D4：视图偏好用 localStorage

卡片/列表偏好按项目记忆，键形如 `grove.view-mode.<projectId>`，默认卡片；纯前端状态，不进后端。列表视图仅展示（标题/目录/类型/来源/更新时间），无排序/筛选/批量。

### D5：项目内搜索交互

知识空间内容区顶部放搜索框，命中整个项目（非当前节点）。有搜索词时进入「搜索结果」模式：隐藏「仅本节点/仅后代」切换，保留「卡片/列表」切换；清空搜索词回到节点浏览。前端用防抖（约 300ms）触发查询。

### D6：全局搜索页面与跳转

`AppShell` 全局导航把「搜索」由禁用项改为 `NavLink` 指向 `/search`；`SearchPage` 复用卡片/列表组件展示结果，并显示所属项目名；点击结果跳 `/projects/{id}?view=directory`（最小跳转，不锚定到具体 Entry）。

### D7：搜索 API 与查询构造

新增 `GET /api/search?q=<关键词>&project_id=<可选>`：

- `project_id` 不传 = 全局（当前 Workspace 全部项目）；传 = 项目内（校验项目归属当前 Workspace）。
- 命中字段：`Entry.title`、`Entry.content`、`Node.name`、`Node.description`、`Source.title`。
- 匹配：`LIKE '%…%'` 大小写不敏感子串；对 `%`、`_`、`\` 转义并用 `ESCAPE` 按字面匹配。
- 构造：`Entry JOIN Node`（目录）、`Entry JOIN Project`（Workspace 隔离）、`Entry JOIN evidences` 用 `EXISTS` 命中 `Source.title`，避免多证据产生重复行。
- 响应：`SearchEntryOut`（在 `EntryOut` 基础上增加 `project_name`），复用 `EntryOut` 的 `node_name` 与含 `source_title` 的证据。

理由：单一接口同时服务项目内与全局搜索；全局结果只需补 `project_name` 即可展示归属，且不改变 Entry 归属。

### D8：无数据库迁移

`source_title` 与 `node_name` 为查询期派生字段，不新增表/列；搜索用现有索引外查询。因此本 change 无 Alembic 迁移。

## Risks / Trade-offs

- [`LIKE '%…%'` 大表性能弱] → P0 数据量为个人知识库，可接受；后续 P1 语义检索再引入索引/向量方案。
- [搜索 OR 多字段 + EXISTS 查询较复杂] → 集中在 `services/search.py` 单测覆盖，避免散落。
- [后代递归在节点很多时多次查询] → 用一次性拉取项目节点后内存构建子树，避免逐层往返。
- [视图偏好仅前端存储，多设备不同步] → 属用户确认的前端偏好，不纳入后端。

## Migration Plan

无数据迁移。仅新增接口与查询参数；`EntryOut`/`EntryEvidenceOut` 为响应新增字段，向后兼容（旧客户端忽略新字段）。回滚即还原代码。

## Open Questions

- 无。搜索字段边界（不含 `note`、不含项目名）与直接/后代语义已与用户对齐。
