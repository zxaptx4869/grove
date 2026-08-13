# node-tree Specification

## Purpose
TBD - created by archiving change add-projects. Update Purpose after archive.
## Requirements
### Requirement: 目录树读取
系统 MUST 提供项目目录树的读取接口，返回按 `position` 顺序嵌套的多级节点树，并且每次读取都校验项目属于当前 Workspace。

#### Scenario: 返回嵌套且有序的树
- **WHEN** 已登录用户请求某项目的目录树
- **THEN** 树结构仅来自当前 Workspace 的该项目，同级节点按存储顺序排列

### Requirement: 节点创建
系统 MUST 支持在目录中创建节点：不传 `parent_id` 时创建为根节点，传 `parent_id` 时创建为其子节点并追加到末尾。

#### Scenario: 创建根节点
- **WHEN** 用户在不指定父节点时创建节点
- **THEN** 新节点成为根级节点

#### Scenario: 创建子节点
- **WHEN** 用户指定同一项目内的父节点创建节点
- **THEN** 新节点出现在该父节点子级末尾

### Requirement: 节点重命名与描述
系统 MUST 支持修改节点名称、描述、父节点和同级顺序；移动操作 MUST 拒绝跨项目父节点和移动到自身/后代，且持久化后树结构保持一致。

#### Scenario: 移动节点
- **WHEN** 用户将节点移动到同项目的另一个父节点
- **THEN** 节点从原父级移除并追加到新父级末尾

#### Scenario: 拒绝非法移动
- **WHEN** 用户将节点移动到自身或其后代
- **THEN** 接口返回 400，原目录树不改变

#### Scenario: 修改生效
- **WHEN** 用户重命名节点或更新描述
- **THEN** 树读取返回更新后的内容

### Requirement: 节点删除与级联
系统 MUST 支持删除节点并级联删除后代；前端对包含子节点的删除 MUST 展示受影响数量并要求二次确认。

#### Scenario: 删除空节点
- **WHEN** 用户确认删除没有子节点的节点
- **THEN** 该节点从树中消失

#### Scenario: 删除子树
- **WHEN** 用户确认删除含后代的节点
- **THEN** 该节点及全部后代从树中消失，并显示完成反馈

#### Scenario: 删除后子树消失
- **WHEN** 用户删除一个含子节点的节点
- **THEN** 该节点及其全部后代从树中消失

### Requirement: 同级节点排序
系统 MUST 支持调整同一父节点下子节点的顺序，顺序变更 MUST 持久化并在树读取中生效。

#### Scenario: 调整顺序后生效
- **WHEN** 用户调整同父节点的顺序
- **THEN** 树读取按新顺序返回，且刷新后保持一致

### Requirement: 目录管理桌面工作台
目录管理 SHALL 作为项目上下文中的独立视图，使用真实目录树 API 和 250px 树栏加剩余内容区的桌面工作台结构。树栏 MUST 承载根节点创建、节点选择和节点上下文操作；内容区 MUST 展示选中节点的路径、名称、可选说明和编辑入口。创建、编辑、移动、排序和删除 SHALL 继续使用真实接口，删除保留二次确认，AI 共创入口 SHALL 明确 Directory Agent 尚未实现。

#### Scenario: 非空目录工作台
- **WHEN** 用户打开包含目录节点的目录管理视图
- **THEN** 页面显示 250px 目录树栏、节点数量、根节点创建动作和剩余内容区，选择节点后显示真实路径、名称、说明和编辑动作

#### Scenario: 空目录工作台
- **WHEN** 用户打开空目录项目的目录管理视图
- **THEN** 页面保持稳定的两栏工作台边界，并在内容区提供“手动创建第一个节点”和“与 AI 共创目录”两个平等入口

#### Scenario: 目录操作状态完整
- **WHEN** 用户创建、编辑、移动、排序或删除目录节点
- **THEN** 相应动作具有 disabled、错误、成功反馈和必要的破坏性确认，操作完成后刷新真实目录树，不显示静态节点

#### Scenario: AI 共创能力未实现
- **WHEN** 用户选择“与 AI 共创目录”
- **THEN** 页面明确说明入口已预留但 Directory Agent 尚未实现，不生成或应用伪目录草稿
