## ADDED Requirements

### Requirement: Entry 来源标题展示
系统 MUST 在 Entry 证据输出中返回来源标题（`source_title`），其值来自证据所指向 Source 的标题；该字段用于卡片与列表的来源展示，不改变证据关系本身。

#### Scenario: 证据含来源标题
- **WHEN** 用户读取一条 Entry 及其证据
- **THEN** 每条证据返回 `source_id`、`attachment_id`、`quote` 与 `source_title`

### Requirement: Entry 按目录浏览
系统 MUST 支持按目录节点读取 Entry，并区分「仅本节点」与「仅后代」两种范围；「仅后代」MUST 只包含该节点严格后代节点的直接 Entry，不含该节点自身；结果 MUST 按创建时间倒序返回；读取 MUST 校验项目属于当前 Workspace。

#### Scenario: 仅本节点
- **WHEN** 用户以「仅本节点」范围读取某节点的 Entry
- **THEN** 只返回主目录为该节点的 Entry，按创建时间倒序

#### Scenario: 仅后代
- **WHEN** 用户以「仅后代」范围读取某节点的 Entry
- **THEN** 返回该节点全部严格后代节点的直接 Entry，不包含该节点自身的直接 Entry

#### Scenario: 越权项目不可见
- **WHEN** 用户请求读取不属于当前 Workspace 项目的 Entry
- **THEN** 请求失败（404），不暴露数据
