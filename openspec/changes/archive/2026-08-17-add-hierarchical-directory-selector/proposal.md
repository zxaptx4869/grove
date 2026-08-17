## Why

确认台归档、批量修改目录和移动节点三处目录选择器目前都是“拍平下拉”，目录一深就无法直观辨认层级，容易选错。Grove 已经有真实嵌套目录树，应该换成可展开、可搜索的层级选择器。

## What Changes

- 新增可复用组件 `DirectoryTreeSelect`：Popover 内展示可展开/收起、带缩进的目录树，触发按钮显示当前选中路径。
- 树内支持按名称与完整路径搜索，命中时自动展开祖先；显示节点直接 Entry 数辅助定位。
- 支持「根目录」选项（父节点场景），组件内记住展开状态（本次会话）。
- 统一替换三处目录选择：确认台归档目录、批量「修改目录」弹窗、知识空间「移动目录节点」父节点。

## Capabilities

### New Capabilities

- `directory-selector`: 层级目录选择器，提供树形浏览、搜索、Entry 数展示与根目录选项。

### Modified Capabilities

无（均为现有功能的交互实现替换，不改变行为语义）。

## Impact

- 前端：新增 `ui/popover` 基础组件与 `DirectoryTreeSelect`；替换 `ReviewPage`、`BatchReviewView`、`ProjectPage` 三处选择控件；更新相关测试。
- 无后端、API 或数据模型变化。

## Non-Goals

- 不改目录树数据模型与接口。
- 不做多选、拖拽排序或目录编辑。
- 不改变「新增节点并归档」与批量确认的业务语义。
