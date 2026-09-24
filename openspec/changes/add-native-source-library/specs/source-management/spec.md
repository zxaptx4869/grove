## MODIFIED Requirements

### Requirement: Source 响应失败信息

`SourceOut` MUST 返回当前可展示的处理失败信息与任务存在性：`failure_reason`（失败文案）、`retry_count`（任务重试次数）与 `has_processing_task`（该来源是否存在处理任务）。`failure_reason` 仅当处理任务处于失败且记录了错误时给出文案，等待处理、处理中、已完成或没有任务时 MUST 为 `null`，不得把历史错误当作当前问题展示；`retry_count` MUST 取任务实际重试次数，来源没有任务时 MUST 为 0；`has_processing_task` MUST 为布尔值，来源有处理任务时为 true、没有任务时为 false，MUST NOT 由状态或等待时长推断。列表、历史查询、创建、幂等命中、详情、修改与触发处理 MUST 返回一致口径，且列表与历史查询 MUST NOT 逐条查询处理任务。

#### Scenario: 处理失败
- **WHEN** 来源的处理任务处于失败并记录了错误
- **THEN** `failure_reason` 为该错误文案，`retry_count` 为任务实际重试次数，`has_processing_task` 为 true

#### Scenario: 当前无失败
- **WHEN** 来源的处理任务处于等待处理、处理中或已完成
- **THEN** `failure_reason` 为 `null`，`retry_count` 为任务实际重试次数，`has_processing_task` 为 true

#### Scenario: 没有处理任务
- **WHEN** 来源从未成功创建处理任务（如处理触发未成功）
- **THEN** `failure_reason` 为 `null`、`retry_count` 为 0、`has_processing_task` 为 false

#### Scenario: 列表与详情口径一致
- **WHEN** 同一来源分别通过来源列表、历史查询与详情读取
- **THEN** 三处的 `failure_reason`、`retry_count` 与 `has_processing_task` 相同，且列表查询的数据库访问次数不随来源条数逐条增长
