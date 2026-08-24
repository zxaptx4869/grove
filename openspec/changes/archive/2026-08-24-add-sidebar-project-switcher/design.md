## Context

进入项目后切换项目需先绕道项目列表页，项目工作台内没有直接切换入口。目标：在项目名旁提供下拉切换，保留当前视图上下文，避免打断整理流。

## Goals / Non-Goals

**Goals:**

- 项目名旁下拉切换项目；
- 下拉列出全部非归档项目并按状态分组；
- 切换时保留当前视图类型；
- 当前项目已归档时下拉中仍可见，保留位置感；
- 非项目页「最近项目」区块保持现状。

**Non-Goals:**

- 下拉内不做项目搜索、创建或归档管理；
- 不调整侧栏宽度、品牌栏、顶栏等壳层几何；
- 沉浸式视图（知识全景 / 思维导图）内不提供切换下拉；
- 不引入新依赖或后端改动。

## Decisions

### D1：数据来源与分组

复用 `useAllProjects`（已按四状态聚合查询，`staleTime: 30s` 与项目列表页一致）。下拉按 `PROJECT_STATUSES` 顺序（进行中 / 暂停 / 已完成）分组渲染全部非归档项目；组内按项目名排序、当前项目置顶并带选中标识。已归档项目不进入常规分组；当前项目为已归档时，在下拉顶部单列展示并带选中标识，避免用户进入已归档项目后丢失位置感。

### D2：切换保留视图

从当前 pathname 提取 `/projects/:id` 段并替换为新项目 id：`/projects/:id`（项目首页）、`/projects/:id?view=directory|ai-read`（知识空间 / AI 阅读）与 `/projects/:id/review`（确认台）均自然保留视图类型，query 参数不变；使用 `navigate()` 普通路由跳转，浏览器历史语义不特殊处理。

### D3：触发与视觉

项目名整块作为 `DropdownMenuTrigger`（ghost 按钮：项目名 + `ChevronDown`），沿用侧栏底部账户菜单的 DropdownMenu 交互模式；原型无对应控件参考，采用现有 shadcn/ui 组件与语义令牌，不硬编码颜色。下拉内容使用 `DropdownMenuLabel` 作为分组标题、`DropdownMenuItem` 作为项目项、`Check` 标识当前项目、底部 `DropdownMenuSeparator` +「全部项目」入口。

### D4：非项目页不显示

下拉只在 `ProjectNavigation`（存在 projectId 时）渲染；`/projects`、`/inbox`、`/search` 等非项目页继续显示「最近项目」区块，两处入口并存，不做统一。

### D5：列表顺序与截断

组内按项目名称排序保持稳定展示；项目名过长使用 `truncate`，下拉固定最小宽度，避免展开时跳动。

## Risks / Trade-offs

- [项目数量增长后列表变长] → 个人项目量级小，全量列出当前足够；后续按真实数据评估是否加搜索，作为蓝图未锁定项记录，不提前实现。
- [30s 缓存导致新建项目不即时出现在下拉] → 与项目列表页行为一致，可接受；下拉打开不强制 refetch。

## Migration Plan

无数据库变更、无接口变更。

## Open Questions

- 无。
