## Context

`refine-sidebar-project-status-icon` 将状态改为纯图标后，用户反馈看不懂；需要恢复文字并以小标签样式呈现。同时保留上一轮已确认的间距收紧（8px）。

## Goals / Non-Goals

**Goals:**

- 状态以「文字 + 边框 + 浅底色」小标签展示，四种状态用语义色区分；
- 切换按钮恢复两行布局（项目名 + 状态标签），与项目导航间距保持 8px；
- 下拉项目项恢复简洁样式，不再使用状态图标。

**Non-Goals:**

- 不改下拉分组、切换保留视图、已归档单列等既有行为；
- 不调整壳层几何与令牌；
- 不引入自定义颜色，仅用现有 `success / warning / confirmed / muted` 语义色。

## Decisions

### D1：状态标签样式

复用 `Badge variant="outline"` 叠加语义色类，与 `BasicsPage` 的连接状态标签、项目列表状态色保持一致：

| 状态 | 标签类 |
|---|---|
| 进行中 | `border-success/30 bg-success-soft text-success` |
| 暂停 | `border-warning/30 bg-warning-soft text-warning` |
| 已完成 | `border-confirmed/30 bg-confirmed-soft text-confirmed` |
| 已归档 | `border-border bg-muted text-muted-foreground` |

标签尺寸 `h-[18px] rounded-md px-1.5 text-[11px] font-normal leading-4`，紧凑不抢项目名视觉。

### D2：切换按钮布局

两行：项目名（`text-[15px] font-[650]`）+ 状态标签；按钮 `py-1.5`；容器 `mb-2`（8px），与项目导航间距保持上一轮收紧值。加载中保持「项目工作台 + 加载中」文字。

### D3：下拉项目项

恢复「左侧选中勾（当前项目）或空白占位 + 项目名」，分组标题已表达状态，项目项不再重复展示状态图标；已归档单列项保留「已归档」文字。

## Risks / Trade-offs

- [两行布局比单行高] → 状态标签需要可读性优先，高度换取信息清晰；间距已收紧到 8px 补偿垂直密度。

## Migration Plan

无数据库变更、无接口变更。

## Open Questions

- 无。
