## Context

当前应用壳在项目路由下只渲染 `ProjectNavigation`（返回、项目名、项目导航），原型则在项目导航下方保留「收集箱」「搜索」全局入口。本 change 只在项目侧栏补两个全局 `NavLink`，不改变壳层宽度或账户入口。

## Goals / Non-Goals

**Goals:**

- 项目侧栏保留「收集箱」「搜索」入口，带真实路由与激活态。
- 与全局导航的视觉样式、高度和交互保持一致。

**Non-Goals:**

- 不在项目侧栏重复「账户」。
- 不实现收集箱或搜索的新业务能力。
- 不调整 216px/184px 侧栏宽度、品牌栏或顶栏。

## Decisions

### D1：入口放在 `ProjectNavigation` 的项目导航之后

在现有项目导航 `<nav>` 结束后添加分隔线与两个 `NavLink`（`/inbox`、`/search`），复用全局导航的 `NavLink` 样式，保证激活态由路由自动切换。

理由：项目侧栏是同一 `ProjectNavigation` 的职责范围，两个入口属于“项目内快速回到全局”的导航，不需要抽取新组件。

### D2：视觉对齐原型

原型基线（来自 `docs/prototypes/grove-product-prototype.html`）：

- 侧栏宽度：216px（1024–1119px 收窄为 184px）；
- 导航项：高 38px、圆角 6px、图标 16px、文字 14px；
- 项目导航与全局入口之间用一条分隔线；
- 全局入口使用与项目导航一致的 hover/激活样式。

实现使用现有 `flex min-h-[38px] items-center gap-[9px] rounded-md px-2.5 text-body` 类名与 `bg-brand-soft`/`text-brand` 激活态；分隔线使用 `my-2 border-t`，与原型 `sidebar-divider` 语义一致。

## Risks / Trade-offs

- [项目侧栏信息变长] → 侧栏已有滚动容器，两个入口高度固定，不会挤压内容区。
- [激活态与全局页冲突] → 使用 `NavLink` 按路由自动判定，收集箱/搜索页激活态与全局侧栏一致。

## Migration Plan

纯前端导航调整，无数据迁移；回滚即移除两个 `NavLink` 与分隔线。

## Open Questions

无。

## 验收结果

- 自动化：前端 40 个测试、lint、build 通过；`openspec validate --all --strict` 通过。
- 浏览器截图：本会话无可用浏览器自动化工具，未生成截图；侧栏为固定 216px/184px 布局内新增两个固定高度导航项，按现有样式类实现，无溢出风险，最终视觉由用户在 1280px、1440px、1600px 下确认。
