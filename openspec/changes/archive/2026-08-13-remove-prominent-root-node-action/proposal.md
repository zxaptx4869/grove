## Why

知识空间页头的绿色“根节点”按钮视觉权重过高，但创建根节点不是高频主任务；同一能力已经在目录树栏右上角提供，重复入口让页面标题区显得喧闹。

## What Changes

- 移除非空知识空间页头的“根节点”主按钮。
- 保留目录树栏右上角的纯图标创建入口，继续提供根节点创建能力。
- 保持空目录中的“手动创建”和“与 AI 共创目录”两个起点不变。

**Non-Goals:**

- 不移除或修改根节点创建能力、接口和对话框。
- 不调整“与 AI 共创目录”、项目菜单、目录树布局或知识空态。
- 不修改后端、数据库或 Workspace 隔离行为。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `node-tree`: 收敛非空知识空间的根节点创建入口层级，取消页头重复主按钮，保留树栏内入口。

## Impact

影响 `frontend/src/pages/ProjectPage.tsx`、对应页面测试和 `node-tree` 主规格；不影响 API、依赖、数据模型或路由。
