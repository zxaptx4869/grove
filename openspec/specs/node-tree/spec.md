# node-tree Specification

## Purpose
TBD - created by archiving change add-projects. Update Purpose after archive.
## Requirements
### Requirement: 目录树读取
系统 MUST 提供项目目录树的读取接口，返回按 `position` 顺序嵌套的多级节点树。

#### Scenario: 返回嵌套且有序的树
- **WHEN** 已登录用户请求某项目的目录树
- **THEN** 返回树结构，同级节点按存储顺序排列，父子层级完整

### Requirement: 节点创建
系统 MUST 支持在目录中创建节点：不传 `parent_id` 时创建为根节点，传 `parent_id` 时创建为其子节点并追加到末尾。

#### Scenario: 创建根节点
- **WHEN** 用户在不指定父节点时创建节点
- **THEN** 新节点成为根级节点

#### Scenario: 创建子节点
- **WHEN** 用户指定父节点创建节点
- **THEN** 新节点出现在该父节点子级末尾

### Requirement: 节点重命名与描述
系统 MUST 支持修改节点的名称与描述。

#### Scenario: 修改生效
- **WHEN** 用户重命名节点或更新描述
- **THEN** 树读取返回更新后的内容

### Requirement: 节点删除与级联
系统 MUST 支持删除节点，删除 MUST 级联删除其全部后代节点。

#### Scenario: 删除后子树消失
- **WHEN** 用户删除一个含子节点的节点
- **THEN** 该节点及其全部后代从树中消失

### Requirement: 同级节点排序
系统 MUST 支持调整同一父节点下子节点的顺序，顺序变更 MUST 持久化并在树读取中生效。

#### Scenario: 调整顺序后生效
- **WHEN** 用户调整同父节点的顺序
- **THEN** 树读取按新顺序返回，且刷新后保持一致

