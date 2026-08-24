## Context

上一个 change（`add-sidebar-project-switcher`）引入侧栏项目切换下拉后，状态文字与按钮两行布局让切换区域偏高，且与项目导航间距（16px）偏大。本次将状态改为图标 + 语义色，并压缩为单行紧凑布局。

## Goals / Non-Goals

**Goals:**

- 四种项目状态用图标 + 语义色一眼区分；
- 切换按钮单行，与项目导航间距收紧到 8px；
- 下拉项目项同步状态图标，可访问名称保持可用。

**Non-Goals:**

- 不改下拉分组、切换保留视图、已归档单列等既有行为；
- 不调整壳层几何与令牌；
- 不引入自定义颜色，仅用现有 `success / warning / confirmed / muted-foreground` 语义色。

## Decisions

### D1：状态图标映射

使用 lucide-react 现有图标与语义色：

| 状态 | 图标 | 语义色 |
|---|---|---|
| 进行中 | `CircleDot` | `text-success` |
| 暂停 | `Pause` | `text-warning` |
| 已完成 | `CircleCheck` | `text-confirmed` |
| 已归档 | `Archive` | `text-muted-foreground` |

图标带 `role="img"` 与 `aria-label`（状态名），保证纯图标状态可访问；按钮本身保留项目名文本。

### D2：切换按钮单行布局

按钮改为一行：状态图标 + 项目名（`truncate`）+ `ChevronDown`；删除状态文字行，`py-1`；容器 `mb-2` 替代 `mb-3 + pb-1`，与项目导航间距由 16px 收紧到 8px。

### D3：下拉项目项

每个项目项左侧显示状态图标（`size-4`，统一占位，不再用空白 span），右侧为当前项目选中勾（`Check` + `text-brand`）；已归档单列项保留「已归档」文字并配归档图标。

## Risks / Trade-offs

- [纯图标状态对色弱用户可读性依赖形状] → 四状态使用不同形状图标（圆点 / 暂停条 / 对勾 / 归档盒），不只靠颜色区分；且下拉分组标题仍保留文字。

## Migration Plan

无数据库变更、无接口变更。

## Open Questions

- 无。
