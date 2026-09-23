# source-management Specification

## Purpose
定义 Source 与 Attachment 的采集、归属、展示与删除，以及未归属来源的管理与 Workspace 隔离。
## Requirements
### Requirement: Source 归属与 Workspace 隔离
系统 MUST 提供 `Source` 模型并归属到 Workspace；Source MUST 可未归属 Project，或最多归属同一 Workspace 内的一个 Project；跨 Workspace 的 Source MUST 不可见。

#### Scenario: 列出当前空间的 Source
- **WHEN** 已登录用户请求收集箱来源列表
- **THEN** 只返回该用户 Workspace 内的 Source

#### Scenario: 跨用户 Source 不可见
- **WHEN** 用户 B 尝试访问用户 A 的 Source（通过 ID）
- **THEN** 请求失败（404），不暴露 Source 信息

### Requirement: 附件与 Source 关系
系统 MUST 支持一个 Source 包含一个或多个 Attachment；Attachment MUST 属于一个 Source，类型为 image（图片）或 text（文字）；同一 Source 的多张图片 MUST 按采集顺序保存。

#### Scenario: 多图来源
- **WHEN** 用户一次上传多张图片采集
- **THEN** 创建一个 Source，其包含多个 image Attachment，并按提交顺序排列

#### Scenario: 文字来源
- **WHEN** 用户粘贴一段文字采集
- **THEN** 创建一个 Source，其包含一个 text Attachment

### Requirement: 图片采集
系统 MUST 支持批量上传图片创建 Source；一次采集的图片数量 MUST 不超过 5 张；采集时 MUST 可选填写所属项目与补充说明；未选择项目时 Source 保持未归属。

#### Scenario: 批量上传并指定项目
- **WHEN** 用户上传多张图片并选择项目
- **THEN** 创建 Source 归属该项目，图片作为附件保存，列表可看到该项目归属

#### Scenario: 上传不选项目
- **WHEN** 用户上传图片但不选择项目
- **THEN** 创建 Source 且未归属任何项目

#### Scenario: 补充说明
- **WHEN** 用户采集时填写补充说明
- **THEN** Source 保存该说明并在列表与详情中可见

#### Scenario: 超过数量上限
- **WHEN** 用户一次上传超过 5 张图片
- **THEN** 请求失败（400），不创建 Source

### Requirement: 文字采集
系统 MUST 支持粘贴文字创建 Source；粘贴图片时按图片处理，纯文字时作为 text Attachment 保存。

#### Scenario: 粘贴纯文字
- **WHEN** 用户粘贴纯文字并采集
- **THEN** 创建 Source 且包含一个 text Attachment

#### Scenario: 粘贴图片
- **WHEN** 用户粘贴图片并采集
- **THEN** 创建 Source 且包含对应的 image Attachment

### Requirement: 本地附件存储与访问
系统 MUST 把图片附件保存在本地文件系统，数据库只存相对路径；上传 MUST 校验文件为支持的图片类型且单张不超过 10MB；图片 MUST 可通过后端接口访问。

#### Scenario: 上传图片后可访问
- **WHEN** 用户上传一张图片
- **THEN** 图片保存到本地附件目录，数据库保存相对路径，前端可通过接口读取该图片

#### Scenario: 拒绝非图片类型
- **WHEN** 用户上传非图片文件
- **THEN** 请求失败（400），不创建 Source

#### Scenario: 拒绝超大图片
- **WHEN** 用户上传单张超过 10MB 的图片
- **THEN** 请求失败（400），不创建 Source

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

### Requirement: Source 详情
Source 详情 MUST 展示其附件（图片缩略图或文字预览）、采集说明、所属项目与创建时间。

#### Scenario: 查看详情
- **WHEN** 用户打开一个 Source 详情
- **THEN** 显示全部附件、采集说明、项目归属和创建时间

### Requirement: 项目归属修改
系统 MUST 支持把未归属 Source 归属到同一 Workspace 内的项目，或修改其所属项目；跨 Workspace 的项目 MUST 被拒绝；已产生正式知识（存在已确认候选或 Entry 证据）的 Source MUST 禁止改归属；处理中（`processing`）的 Source MUST 禁止改归属。

#### Scenario: 选择项目
- **WHEN** 用户把未归属 Source 归属到某个项目
- **THEN** Source 更新为归属该项目

#### Scenario: 拒绝跨空间项目
- **WHEN** 用户尝试把 Source 归属到其他 Workspace 的项目
- **THEN** 请求失败（400），归属不改变

#### Scenario: 已产生正式知识禁止改归属
- **WHEN** 用户尝试修改已产生正式知识的 Source 的所属项目
- **THEN** 请求失败（409），归属不改变，并返回可读原因

#### Scenario: 处理中禁止改归属
- **WHEN** 用户尝试修改处理中（`processing`）的 Source 的所属项目
- **THEN** 请求失败（409），归属不改变，并返回可读原因

#### Scenario: 提取完成未确认可改归属
- **WHEN** 用户尝试修改提取完成但候选尚未确认、且未产生正式知识的 Source 的所属项目
- **THEN** 归属修改成功，待确认候选随之重新路由

### Requirement: 删除 Source
系统 MUST 支持删除 Source 并级联删除其 Attachment 记录、来源证据、候选与本地附件文件；已产生正式知识（存在 Entry 来源证据）的 Source MUST 禁止删除；处理中（`processing`）的 Source MUST 禁止删除；存在待确认候选时，前端 MUST 在删除前二次确认并提示将连带删除候选。

#### Scenario: 删除清理附件
- **WHEN** 用户删除一个含图片的 Source
- **THEN** Source 及其 Attachment 记录被删除，本地图片文件也被清理

#### Scenario: 已产生正式知识禁止删除
- **WHEN** 用户尝试删除已产生正式知识的 Source
- **THEN** 请求失败（409），Source 与证据保持不变

#### Scenario: 处理中禁止删除
- **WHEN** 用户尝试删除处理中（`processing`）的 Source
- **THEN** 请求失败（409），Source 保持不变

#### Scenario: 有待确认候选删除需确认
- **WHEN** 用户删除存在 N 条待确认候选、未产生正式知识的 Source
- **THEN** 前端提示将连带删除 N 条候选并要求确认，确认后执行删除

#### Scenario: 已产生正式知识的来源不展示操作
- **WHEN** 用户查看已产生正式知识的 Source 行
- **THEN** 该行不展示改归属下拉与删除按钮

### Requirement: Source 响应状态字段
`SourceOut` MUST 返回 `project_locked`（是否禁止改归属）与 `evidence_entry_count`（被多少条正式 Entry 引用），供前端按状态收敛操作。

#### Scenario: 锁定标记
- **WHEN** Source 已被确认候选或 Entry 证据引用
- **THEN** `project_locked=true`，前端禁用改归属入口

#### Scenario: 证据计数
- **WHEN** Source 被 N 条 Entry 引用
- **THEN** `evidence_entry_count=N`，前端据此展示删除确认文案

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

### Requirement: Source 处理状态与触发
Source MUST 有处理状态（等待处理 / 处理中 / 提取完成 / 失败）；采集后 MUST 默认为等待处理；来源列表 MUST 展示状态，并对等待处理提供「开始处理」、对失败提供「重试」。

#### Scenario: 采集后等待处理
- **WHEN** 用户采集一个 Source
- **THEN** Source 状态为等待处理

#### Scenario: 展示状态
- **WHEN** 用户查看来源列表
- **THEN** 每条 Source 展示其处理状态，提取完成状态文案为「提取完成」

#### Scenario: 开始处理
- **WHEN** 用户对等待处理的 Source 点击「开始处理」
- **THEN** Source 进入处理流程，状态变为处理中

#### Scenario: 失败重试
- **WHEN** 用户对失败的 Source 点击「重试」
- **THEN** Source 重新进入处理流程

### Requirement: Source 审阅状态
系统 MUST 根据 Source 当前候选的决策结果派生审阅状态，并在来源列表以副徽标展示：有待确认候选时显示「待确认 N 条」，已有正式知识且仍有待确认时显示「部分确认」，已产生正式知识且无待确认时显示「N 条正式知识」，无待确认且无正式知识时显示「已处理」；`SourceOut` MUST 返回 `pending_candidate_count`（待确认候选数）；确认台待处理来源 MUST 只展示仍有待采纳候选的来源。

#### Scenario: 处理完成后待确认
- **WHEN** Source 处理成功并产生候选，且候选都未决策
- **THEN** 该来源出现在待处理来源列表，审阅状态为待确认

#### Scenario: 部分确认
- **WHEN** Source 的候选部分已采纳或已拒绝，但仍有待采纳
- **THEN** 该来源出现在待处理来源列表，审阅状态为部分确认

#### Scenario: 全部处理完成
- **WHEN** Source 的全部候选都已是已采纳或已拒绝
- **THEN** 该来源视为已处理，不再出现在待处理来源列表

#### Scenario: 待确认副徽标
- **WHEN** 提取完成且存在 N 条待确认候选、无正式知识
- **THEN** 来源行显示「待确认 N 条」，可改归属与删除

#### Scenario: 部分确认副徽标
- **WHEN** 提取完成且已有正式知识、仍有待确认候选
- **THEN** 来源行显示「部分确认」，并锁定改归属与删除

#### Scenario: 正式知识副徽标
- **WHEN** 提取完成且已产生 N 条正式知识、无待确认候选
- **THEN** 来源行显示「N 条正式知识」，并锁定改归属与删除

#### Scenario: 已处理副徽标
- **WHEN** 提取完成、候选全部拒绝且无正式知识
- **THEN** 来源行显示「已处理」，可改归属与删除

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

