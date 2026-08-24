## Why

侧栏项目切换区域的状态目前用文字小字展示，四种状态不易一眼区分；切换按钮为两行布局，与下方项目导航间距偏大，侧栏信息密度偏低。

## What Changes

- 项目名切换按钮由两行改为单行：状态以「图标 + 语义色」标识（进行中 / 暂停 / 已完成 / 已归档），不再单独占一行文字。
- 下拉中的项目项同步增加状态图标，当前项目在右侧保留选中勾；已归档单列项保留「已归档」文字并配归档图标。
- 收紧切换区域与项目导航的间距（16px → 8px），保持单行紧凑布局。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `product-shell`: 项目侧栏切换区域的状态展示改为图标 + 语义色，并收紧与项目导航的间距。

## Impact

- 前端：仅修改 `frontend/src/components/layout/AppShell.tsx`（状态图标常量与 `ProjectNavigation` 布局）及对应测试；无后端、API、数据库变化。
- 测试：更新 AppShell 测试断言状态图标；`npm run lint`、`npm run test`、`npm run build`。

## Non-Goals

- 不改变下拉的内容、分组、切换保留视图等既有行为。
- 不调整侧栏宽度、品牌栏、顶栏结构。
- 不引入新的状态色或图标令牌以外的自定义颜色。
