## MODIFIED Requirements

### Requirement: Source 列表

系统 MUST 支持列出当前 Workspace 的 Source，并按未归属或指定项目筛选，且 MUST 支持 `limit` 参数限制返回条数（用于收集箱「最近来源」）；项目内来源列表 MUST 只返回该项目内的 Source。

#### Scenario: 收集箱未归属筛选
- **WHEN** 用户查看收集箱并筛选未归属
- **THEN** 只返回未归属项目的 Source

#### Scenario: 项目内来源
- **WHEN** 用户在项目内查看采集与来源
- **THEN** 只返回归属该项目的 Source

#### Scenario: 最近来源限制条数
- **WHEN** 收集箱请求最近来源并携带 limit
- **THEN** 只返回按创建时间倒序的前 limit 条 Source

### Requirement: 全量来源历史查询

系统 MUST 提供全量来源历史查询：支持项目、处理状态与未归属筛选，支持关键词搜索（标题或备注），支持分页（limit/offset）并返回总条数；查询 MUST 限定当前 Workspace。

#### Scenario: 按项目筛选历史
- **WHEN** 用户在来源历史页选择某项目
- **THEN** 只返回归属该项目的 Source

#### Scenario: 按状态筛选历史
- **WHEN** 用户在来源历史页选择处理状态
- **THEN** 只返回该状态的 Source

#### Scenario: 关键词搜索
- **WHEN** 用户在来源历史页输入关键词
- **THEN** 只返回标题或备注包含关键词的 Source

#### Scenario: 分页返回总数
- **WHEN** 用户翻页查看来源历史
- **THEN** 每页返回 limit 条（默认 20），并返回符合条件的总条数

#### Scenario: 越权查询不可见
- **WHEN** 查询的项目不属于当前 Workspace
- **THEN** 请求失败（404），不返回数据

### Requirement: 项目归属修改

系统 MUST 支持把未归属 Source 归属到同一 Workspace 内的项目，或修改其所属项目；跨 Workspace 的项目 MUST 被拒绝；已有确认候选或 Entry 来源证据的 Source MUST 禁止改归属。

#### Scenario: 选择项目
- **WHEN** 用户把未归属 Source 归属到某个项目
- **THEN** Source 更新为归属该项目

#### Scenario: 拒绝跨空间项目
- **WHEN** 用户尝试把 Source 归属到其他 Workspace 的项目
- **THEN** 请求失败（400），归属不改变

#### Scenario: 已归档来源禁止改归属
- **WHEN** 用户尝试修改已被确认候选或 Entry 证据引用的 Source 的所属项目
- **THEN** 请求失败（409），归属不改变，并返回可读原因

### Requirement: 删除 Source

系统 MUST 支持删除 Source 并级联删除其 Attachment 记录与本地附件文件；当该 Source 是某正式 Entry 的唯一来源证据时 MUST 阻止删除；被多条 Entry 引用但非唯一证据时，前端 MUST 在删除前二次确认并提示影响条数。

#### Scenario: 删除清理附件
- **WHEN** 用户删除一个含图片的 Source
- **THEN** Source 及其 Attachment 记录被删除，本地图片文件也被清理

#### Scenario: 唯一证据阻止删除
- **WHEN** 用户删除某正式 Entry 的唯一来源证据 Source
- **THEN** 请求失败（409），Source 与证据保持不变

#### Scenario: 其他证据删除需确认
- **WHEN** 用户删除被多条 Entry 引用但非唯一证据的 Source
- **THEN** 前端提示影响条数并要求确认，确认后执行删除

### Requirement: Source 响应状态字段

`SourceOut` MUST 返回 `project_locked`（是否禁止改归属）与 `evidence_entry_count`（被多少条正式 Entry 引用），供前端按状态收敛操作。

#### Scenario: 锁定标记
- **WHEN** Source 已被确认候选或 Entry 证据引用
- **THEN** `project_locked=true`，前端禁用改归属入口

#### Scenario: 证据计数
- **WHEN** Source 被 N 条 Entry 引用
- **THEN** `evidence_entry_count=N`，前端据此展示删除确认文案
