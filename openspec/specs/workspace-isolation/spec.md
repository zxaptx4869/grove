# workspace-isolation Specification

## Purpose
TBD - created by archiving change add-user-auth. Update Purpose after archive.
## Requirements
### Requirement: Workspace 模型与注册自动创建
系统 MUST 提供 `Workspace` 模型；用户注册成功时 MUST 自动创建其默认 Workspace，并将用户登记为该 Workspace 的 owner。`workspace_members` 关系 MUST 使用多对多建模，为未来推广预留（v1 每个用户仅有一个空间，无切换/邀请功能）。

#### Scenario: 注册即拥有默认空间
- **WHEN** 新用户完成注册
- **THEN** 系统自动创建一个 Workspace，且该用户是其 owner

### Requirement: 当前 Workspace 依赖注入
后端 MUST 提供 `get_current_workspace` FastAPI 依赖：基于当前用户解析其默认 Workspace；未登录或无法解析时 MUST 返回 401。

#### Scenario: 已登录用户解析当前空间
- **WHEN** 已登录用户访问需要空间上下文的接口
- **THEN** 业务代码可获得该用户的默认 Workspace

### Requirement: 跨 Workspace 数据隔离
所有业务查询与写入 MUST 以当前 Workspace 为边界：查询结果只包含当前空间的数据；任何跨空间访问 MUST 不可见。违反该不变量视为缺陷（AGENTS.md 铁律）。

#### Scenario: 用户只能看到自己空间的数据
- **WHEN** 用户 A 与用户 B 各自注册（各自拥有独立 Workspace）并查询业务数据
- **THEN** A 的结果不包含 B 空间的数据，B 亦然；A 无法通过构造参数访问 B 的空间数据

