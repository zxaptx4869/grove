## ADDED Requirements

### Requirement: 采集幂等键

系统 MUST 支持 `POST /api/sources` 携带可选 multipart 字段 `capture_key`，并 MUST 在同一 Workspace 内按该键唯一。同键请求第二次到达时 MUST 直接返回已存在的 Source（200），MUST NOT 新建 Source、新增附件或写入新的本地文件；未命中时 MUST 按现有采集流程创建（201）并保存该键。键 MUST 为 1–128 个字符，超限 MUST 返回 400；未携带（或仅空白）时行为 MUST 与变更前一致。唯一性 MUST 限定在 Workspace 内，跨 Workspace 的同键 MUST NOT 互相命中。并发同键 MUST 由唯一约束兜底：冲突后回查已存在记录并返回 200，且该次调用已写入的文件 MUST 被清理。幂等命中检查 MUST 早于本地文件写入。

#### Scenario: 同键重复提交
- **WHEN** 同一 Workspace 内客户端用相同 `capture_key` 再次提交（弱网重试）
- **THEN** 请求返回 200 与第一次创建的 Source，不新增 Source、不新增附件、不写入新的本地文件

#### Scenario: 不同键或未携带键
- **WHEN** 用户用新的 `capture_key` 提交，或请求未携带 `capture_key`
- **THEN** 系统创建新的 Source 并返回 201；未携带键时行为与变更前一致

#### Scenario: 跨 Workspace 同键不命中
- **WHEN** 用户 B 使用与用户 A 相同的 `capture_key` 提交采集
- **THEN** 系统为用户 B 创建新的 Source 并返回 201，不返回用户 A 的记录

#### Scenario: 键长度超限
- **WHEN** 请求携带长度超过 128 的 `capture_key`
- **THEN** 请求失败（400），不创建 Source

#### Scenario: 并发同键冲突
- **WHEN** 两个并发请求携带同一 Workspace 内的相同 `capture_key`
- **THEN** 只有一个请求创建 Source，另一个由唯一约束兜底回查并返回已存在的 Source（200），且该请求已落盘的文件被清理

### Requirement: Source 响应失败信息

`SourceOut` MUST 返回当前可展示的处理失败信息：`failure_reason`（失败文案）与 `retry_count`（任务重试次数）。`failure_reason` 仅当处理任务处于失败且记录了错误时给出文案，等待处理、处理中、已完成或没有任务时 MUST 为 `null`，不得把历史错误当作当前问题展示；`retry_count` MUST 取任务实际重试次数，来源没有任务时 MUST 为 0。列表、历史查询、创建、幂等命中、详情、修改与触发处理 MUST 返回一致口径，且列表与历史查询 MUST NOT 逐条查询处理任务。

#### Scenario: 处理失败
- **WHEN** 来源的处理任务处于失败并记录了错误
- **THEN** `failure_reason` 为该错误文案，`retry_count` 为任务实际重试次数

#### Scenario: 当前无失败
- **WHEN** 来源的处理任务处于等待处理、处理中或已完成，或该来源没有处理任务
- **THEN** `failure_reason` 为 `null`，`retry_count` 在无任务时为 0，有任务时为任务实际重试次数

#### Scenario: 列表与详情口径一致
- **WHEN** 同一来源分别通过来源列表、历史查询与详情读取
- **THEN** 三处的 `failure_reason` 与 `retry_count` 相同，且列表查询的数据库访问次数不随来源条数逐条增长

## MODIFIED Requirements

### Requirement: 标题自动生成

系统 MUST 在采集时生成初始标题：请求携带非空 `title` 时 MUST 使用该值（strip 后截断 255）；未携带、空串或仅空白时，图片 Source 取第一个图片附件的文件名，文字 Source 取正文首行。处理成功后 MUST 用 Organizing Agent 生成的非空标题更新 Source 标题；采集阶段 MUST NOT 依赖 AI 生成标题。

#### Scenario: 客户端指定标题
- **WHEN** 用户采集时携带 `title`
- **THEN** Source 初始标题为该传入值，而不是第一个图片文件名或正文首行

#### Scenario: 仅空白标题按缺省处理
- **WHEN** 用户采集时携带仅含空白字符的 `title`
- **THEN** Source 标题按未携带处理，图片取第一个文件名、文字取正文首行

#### Scenario: 图片标题
- **WHEN** 用户上传图片创建 Source 且未携带 `title`
- **THEN** Source 初始标题为第一个图片文件名

#### Scenario: 文字标题
- **WHEN** 用户粘贴文字创建 Source 且未携带 `title`
- **THEN** Source 初始标题为正文首行

#### Scenario: 处理完成后更新 AI 标题
- **WHEN** Source 处理成功且 Agent 生成了非空标题
- **THEN** Source 标题更新为该 AI 标题
