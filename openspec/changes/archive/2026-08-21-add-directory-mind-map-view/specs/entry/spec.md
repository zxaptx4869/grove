## MODIFIED Requirements

### Requirement: Entry 按目录浏览
系统 MUST 支持按目录节点读取 Entry，并区分「仅本节点」「仅后代」与「包含子树」三种范围；「仅后代」MUST 只包含该节点严格后代节点的直接 Entry，不含该节点自身；「包含子树」MUST 包含该节点自身的直接 Entry 及其全部严格后代节点的直接 Entry；结果 MUST 按创建时间倒序返回；读取 MUST 校验项目属于当前 Workspace。

#### Scenario: 仅本节点
- **WHEN** 用户以「仅本节点」范围读取某节点的 Entry
- **THEN** 只返回主目录为该节点的 Entry，按创建时间倒序

#### Scenario: 仅后代
- **WHEN** 用户以「仅后代」范围读取某节点的 Entry
- **THEN** 返回该节点全部严格后代节点的直接 Entry，不包含该节点自身的直接 Entry

#### Scenario: 包含子树
- **WHEN** 用户以「包含子树」范围读取某节点的 Entry
- **THEN** 返回该节点自身的直接 Entry 与全部严格后代节点的直接 Entry，按创建时间倒序

#### Scenario: 越权项目不可见
- **WHEN** 用户请求读取不属于当前 Workspace 项目的 Entry
- **THEN** 请求失败（404），不暴露数据

## ADDED Requirements

### Requirement: Entry 按项目读取
系统 MUST 支持读取某项目全部已确认 Entry，结果 MUST 按创建时间倒序返回；读取 MUST 校验项目属于当前 Workspace。

#### Scenario: 返回项目全部 Entry
- **WHEN** 用户读取某项目的全部 Entry
- **THEN** 返回该项目全部已确认 Entry，按创建时间倒序

#### Scenario: 越权项目不可见
- **WHEN** 用户请求读取不属于当前 Workspace 项目的全部 Entry
- **THEN** 请求失败（404），不暴露数据
