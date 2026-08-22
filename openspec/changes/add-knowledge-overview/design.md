## Context

思维导图已完成并归档（`directory-mind-map` 主规格）；旭日图此前以静态原型（`docs/prototypes/grove-knowledge-overview.html`）与临时 React 页（git 历史中的 `KnowledgeOverviewPrototype.tsx`）验证过交互与视觉。本 change 把旭日图正式化为「知识全景」视图，并与思维导图合并为单一入口、顶部切换，解决「两个独立入口导航复杂」的问题。

可复用资产：树接口（`entry_count`）、`nodes/{id}/entries`（direct/subtree）、`projects/{id}/entries`、共享组件 `EntryPopover`，以及已归档的「直接 / 后代 / 合计」计数口径与产品专题表述。

## Goals / Non-Goals

**Goals:**
- 提供项目级「知识全景」沉浸视图（`view=overview`），默认旭日图，顶部「旭日图 | 思维导图」切换；
- 旭日图实现全局结构/知识密度认知：单色扇区、宽度=合计数、hover 高亮与计数、钻取、标签缩写、缩放平移（零依赖）；
- 跨模式联动：旭日图节点 ↔ 思维导图聚焦，双向可达；
- 入口收敛：知识空间页头与项目首页只保留「知识全景」入口；
- 后端零改动、无新增依赖。

**Non-Goals:**
- 不在知识全景中提供目录/知识的编辑、移动、删除与拖拽；
- 不做项目首页全景卡（已否决）；
- 不做旭日图与思维导图同屏并排（同视图内切换、不同屏展示）；
- 旭日图不承担全文阅读（悬浮窗仅预览与来源查看）；
- 不引入图/脑图第三方库；不实现手机 Web 业务界面。

## Decisions

### 1. 视图与路由：`view=overview` + `mode` 参数
知识全景以项目级参数视图承载（与 `view=directory`、`view=ai-read` 同构）：`view=overview&mode=sunburst|mindmap`，模式由 URL 驱动（单一来源、可深链、刷新保持）。旧 `view=mindmap` 入口在前端做兼容重定向到 `view=overview&mode=mindmap`，避免历史链接失效。

备选：独立路由 `/projects/:id/overview`。参数式与本仓库既有视图风格一致，路由改动最小，采用参数式。

### 2. 模式切换与状态保留
顶部用 segmented 切换（旭日图 | 思维导图）。两个模式组件同时挂载、用显隐切换（保留各自内部状态：旭日图钻取层级、思维导图展开/收起/聚焦），避免来回切换丢上下文。两者共用同一 `project-tree` 查询键，缓存天然共享。

### 3. 旭日图实现：从原型恢复 + viewBox 缩放
- 几何与交互从 git 历史 `KnowledgeOverviewPrototype.tsx` 恢复并组件化（`SunburstPanel`），视觉与静态原型一致：按深度单色、宽度=合计数、hover 祖先高亮 + 「直接/后代/合计」悬浮窗、点击钻取 + 面包屑、标签按弧长缩写 + hover 补名；
- 缩放采用 **SVG viewBox 动态化**（改 `x y w h`），滚轮以光标为中心（保持光标下的点不动：按缩放前后坐标换算），配套放大/缩小/「适应窗口」按钮；不依赖第三方库。标签随缩放同比例变化（与地图类软件一致），首版不做反缩放；
- 右侧目录大纲联动 + 直接知识列表 + `EntryPopover` 悬浮详情（hover 预览、点击固定），与思维导图体验一致。

### 4. 跨模式联动
旭日图选中节点 → 「在思维导图中查看」：`setSearchParams({ view:'overview', mode:'mindmap', node:id })`；`MindMapView` 已支持 `node` 参数定位，切换后直接聚焦该节点。思维导图极简阅读栏增加「查看全景」：切回 `mode=sunburst` 并保持节点。

### 5. 入口收敛
`ProjectPage` 知识空间页头与项目首页的「思维导图」按钮替换为「知识全景」（默认 `view=overview`）；「在知识空间中打开」桥接（`view=directory&node=`）保持不变。`AppShell` 沉浸式条件由 `view=mindmap` 扩展为覆盖 `view=overview`。

## Risks / Trade-offs

- [旧 `view=mindmap` 链接失效] → ProjectPage 对 `view=mindmap` 做兼容重定向到 `view=overview&mode=mindmap`。
- [缩放后标签过大/过小] → 首版接受（地图式体验）；如反馈不佳，后续单独做标签反缩放。
- [大目录扇区过多导致 SVG 性能下降] → 设可见扇区上限（建议 300，待真实数据校准），超出提示钻取；必要时后续评估 canvas。
- [双模式同时挂载的内存与查询] → 两模式共享 tree 查询；其余按需懒查，可接受。
- [归档工具按场景名匹配，旧场景名无法重命名] → `directory-mind-map` 与 `node-tree` 的 MODIFIED 块保留原场景名但更新内容（如「知识空间思维导图入口」内容改为知识全景入口），命名差异记录于此。

## Migration Plan

- 无数据库变更；前端兼容重定向旧 `view=mindmap`；
- 回滚：保留 `view=mindmap` 兼容分支即可恢复旧入口，不影响已归档主规格。

## Open Questions

- 旭日图可见扇区上限的具体数值（300？）待真实数据校准；
- 模式切换默认保留状态（当前决策），实际使用占比待上线后验证；
- 大纲联动是否首版保留（当前决策保留），若空间紧张可折叠为可选面板。

## 走查修订（2026-08-22）

- 缩放按钮方向修正：viewBox 数值变小为放大、变大为缩小；
- 旭日图尺寸稳定：环厚按项目完整深度恒定，钻取后保持固定视图、不自动放大适配，「适应窗口」回到完整画布；浅层节点显示正常环厚的小圆，避免撑满；
- 侧栏知识支持「包含子树」勾选（默认勾选，范围 `subtree`），并移除重复的「当前节点」块；
- 入口按钮：知识全景入口保留文字按钮；侧栏跨模式/跳转桥接改为图标按钮（Network / FolderInput，带 tooltip）。
