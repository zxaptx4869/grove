## ADDED Requirements

### Requirement: 关键词搜索字段与匹配
系统 MUST 提供关键词搜索，命中 `Entry.title`、`Entry.content`、目录节点名称与说明，以及来源标题（`Source.title`）；匹配 MUST 使用大小写不敏感的子串匹配，并对用户输入中的 `%` 与 `_` 做转义，按字面匹配。

#### Scenario: 命中标题或内容
- **WHEN** 用户输入的关键词出现在某条 Entry 的标题或核心内容中
- **THEN** 该 Entry 出现在搜索结果中

#### Scenario: 命中目录
- **WHEN** 用户输入的关键词出现在某条 Entry 主目录节点的名称或说明中
- **THEN** 该 Entry 出现在搜索结果中

#### Scenario: 命中来源摘要
- **WHEN** 用户输入的关键词出现在某条 Entry 证据所指向 Source 的标题中
- **THEN** 该 Entry 出现在搜索结果中

#### Scenario: 通配符按字面匹配
- **WHEN** 用户输入包含 `%` 或 `_`
- **THEN** 系统按字面匹配这些字符，不把它们当作 SQL 通配符

### Requirement: 项目内关键词搜索
系统 MUST 支持在指定项目内搜索已确认 Entry；搜索范围 MUST 限定在同一个 Workspace 的该项目内；无匹配时 MUST 返回空结果。

#### Scenario: 项目内搜索
- **WHEN** 用户在某个项目内输入关键词并搜索
- **THEN** 只返回该项目内命中关键词的 Entry

#### Scenario: 越权项目不可见
- **WHEN** 用户请求搜索不属于当前 Workspace 的项目
- **THEN** 请求失败（404），不暴露其他 Workspace 数据

### Requirement: 全局关键词搜索
系统 MUST 支持跨当前 Workspace 全部项目搜索已确认 Entry；结果 MUST 展示每条 Entry 所属项目，且 MUST NOT 改变 Entry 的项目归属；点击结果 SHALL 跳转到对应项目的知识空间。

#### Scenario: 跨项目命中
- **WHEN** 用户从全局搜索输入关键词
- **THEN** 返回当前 Workspace 内所有项目命中的 Entry，并标注各自项目名

#### Scenario: 不改变归属
- **WHEN** 用户查看全局搜索结果
- **THEN** Entry 的项目归属保持不变

#### Scenario: 跳转项目知识空间
- **WHEN** 用户点击一条全局搜索结果
- **THEN** 页面跳转到该 Entry 所属项目的知识空间
