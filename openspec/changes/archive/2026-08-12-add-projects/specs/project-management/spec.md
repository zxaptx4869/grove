## ADDED Requirements

### Requirement: 多项目归属与列表
系统 MUST 提供 `Project` 模型并归属到 Workspace；已登录用户 MUST 只能看到自己 Workspace 内的项目；跨 Workspace 的项目 MUST 不可见。

#### Scenario: 列出当前空间的项目
- **WHEN** 已登录用户请求项目列表
- **THEN** 只返回该用户 Workspace 内的项目

#### Scenario: 跨用户项目不可见
- **WHEN** 用户 B 尝试访问用户 A 的项目（通过 ID）
- **THEN** 请求失败（404），不暴露项目信息

### Requirement: 创建项目并选择目录模板
系统 MUST 支持创建项目，创建时 MUST 选择模板：`decoration`（装修模板）或 `empty`（空目录）；选择装修模板时 MUST 生成完整模板树。

#### Scenario: 装修模板生成完整树
- **WHEN** 以 `decoration` 模板创建项目
- **THEN** 项目创建成功，且其目录树包含模板中的全部节点（149 个）

#### Scenario: 空目录创建
- **WHEN** 以 `empty` 模板创建项目
- **THEN** 项目创建成功且目录树为空

### Requirement: 项目重命名与删除
系统 MUST 支持重命名项目；删除项目 MUST 级联删除其全部目录节点。

#### Scenario: 重命名生效
- **WHEN** 用户重命名项目
- **THEN** 项目列表与详情返回新名称

#### Scenario: 删除项目级联清理
- **WHEN** 用户删除一个含目录树的项目
- **THEN** 项目及其全部节点均被删除，列表不再包含该项目
