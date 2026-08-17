## Context

三处目录选择（确认台归档、批量统一目录、移动节点父节点）都使用拍平 `<select>`。现有目录树接口返回嵌套 `TreeNodePayload`，因此新增共享层级选择器是纯前端改造。

## Goals / Non-Goals

**Goals:**

- 一个可复用 `DirectoryTreeSelect` 组件覆盖三处。
- 树形浏览 + 搜索 + Entry 数 + 展开记忆 + 根目录选项。

**Non-Goals:**

- 不改变后端与数据模型。
- 不做多选、拖拽或目录编辑。
- 不改变确认/批量/移动的业务语义。

## Decisions

### D1：用 Radix Popover + 自定义树面板

仓库已依赖 `radix-ui` 统一包，新增 `ui/popover.tsx` 基础组件，`DirectoryTreeSelect` 在其内实现搜索框与树列表。触发按钮展示当前选中路径，宽度与现有表单控件一致。

理由：Radix Popover 提供焦点管理、点击外部关闭与定位，避免手写弹层；树面板按现有 `NodeTree` 的行高、缩进和语义色实现。

### D2：树渲染与过滤

- 无搜索时：按 `expandedIds` 展开状态渲染可见行，缩进 `depth * 16px`。
- 有搜索时：按名称与完整路径过滤，自动展开所有命中节点的祖先，隐藏无关分支。
- 每行显示：展开箭头（有子节点时）、文件夹图标、名称、直接 `entry_count`。

### D3：组件 API

```tsx
<DirectoryTreeSelect
  nodes={nodes}
  value={nodeId | null}
  allowRoot?: boolean
  loading?: boolean
  placeholder?: string
  ariaLabel?: string
  filter?: (node: TreeNodePayload) => boolean
  onSelect={(nodeId | null) => void}
/>
```

`filter` 用于移动节点时排除自身与后代；`allowRoot` 用于父节点场景。

### D4：三处接入

- `ReviewPage`：归档目录替换为 `DirectoryTreeSelect`（任意层级可选），保留推荐提示与「新增节点并归档」动作。
- `BatchReviewView`：修改目录弹窗内替换统一目录下拉。
- `ProjectPage`：移动节点弹窗替换父节点下拉，传 `filter` 排除自身/后代，`allowRoot`。

## Risks / Trade-offs

- [Popover 在窄容器内溢出] → 面板固定宽度 320px、树区 `max-h-80` 滚动，触发按钮文本截断。
- [深层目录浏览成本] → 搜索按完整路径过滤并自动展开祖先兜底。
- [移动节点候选过滤复杂] → 复用现有 `findNodeWithPath` 逻辑，只把过滤后的子树传给组件。

## Migration Plan

纯前端替换，无迁移；回滚即恢复旧下拉。

## Open Questions

无。
