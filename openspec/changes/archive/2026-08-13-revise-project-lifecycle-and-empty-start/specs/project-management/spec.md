## RENAMED Requirements

- FROM: `### Requirement: 创建项目并选择目录模板`
- TO: `### Requirement: 创建项目并默认空目录`

## MODIFIED Requirements

### Requirement: 多项目归属与列表
系统 MUST 提供 `Project` 模型并归属到 Workspace；已登录用户 MUST 只能看到自己 Workspace 内的项目；跨 Workspace 的项目 MUST 不可见。项目列表 MUST 支持按进行中、暂停、已完成、已归档筛选，已归档项目默认不出现在非归档列表中。

#### Scenario: 列出当前空间的项目
- **WHEN** 已登录用户请求项目列表
- **THEN** 只返回该用户 Workspace 内且符合状态筛选的项目

#### Scenario: 跨用户项目不可见
- **WHEN** 用户 B 尝试访问用户 A 的项目（通过 ID）
- **THEN** 请求失败（404），不暴露项目信息

### Requirement: 创建项目并默认空目录
系统 MUST 支持创建项目，创建请求包含名称以及可选的项目目标与背景说明；新项目 MUST 默认状态为进行中且目录树为空。系统 MUST NOT 要求或展示装修模板选择。

#### Scenario: 创建空项目
- **WHEN** 用户提交合法名称，可选择填写目标与背景
- **THEN** 项目创建成功，状态为进行中，返回的目录节点数为 0

#### Scenario: 背景可选
- **WHEN** 用户不填写目标与背景
- **THEN** 项目仍可创建，说明字段为空

#### Scenario: 装修模板生成完整树
- **WHEN** 历史客户端仍以 `decoration` 模板参数调用兼容接口
- **THEN** 后端可继续生成旧模板树，但正式前端不展示该入口

#### Scenario: 空目录创建
- **WHEN** 正式前端创建项目或历史客户端以 `empty` 参数创建项目
- **THEN** 项目创建成功且目录树为空
