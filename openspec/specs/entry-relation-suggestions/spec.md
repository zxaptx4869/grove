# entry-relation-suggestions Specification

## Purpose
为候选判断与已有 Entry 的关系（新建/重复/补充/冲突），支持补充来源证据与应用修订草稿，冲突候选进入精审。
## Requirements
### Requirement: 项目内相似 Entry 检索

系统 MUST 在候选进入确认台前，于候选所属项目内检索相似正式 Entry；检索范围 MUST 限定当前 Workspace 的同一项目；检索 MUST 使用关键词与字符重叠等确定性召回，不得跨项目或跨 Workspace 检索。

#### Scenario: 项目内有相似 Entry

- **WHEN** 候选所属项目内存在标题或内容相近的正式 Entry
- **THEN** 系统返回这些 Entry 供关系判断使用

#### Scenario: 项目内没有 Entry

- **WHEN** 候选所属项目内没有任何正式 Entry
- **THEN** 系统不调用关系判断，候选关系状态为 `new`

#### Scenario: 不跨项目检索

- **WHEN** 项目内检索相似 Entry
- **THEN** 只检索该候选所属项目的 Entry，不返回其他项目或其他 Workspace 的 Entry

### Requirement: 关系建议落库

系统 MUST 为每条待采纳候选保存关系建议，字段 MUST 包括 `relation_status`（`pending` / `new` / `duplicate` / `supplement` / `conflict`）、`relation_target_entry_id`（可空）、`relation_reason`（可空）与 `revision_draft`（可空）；未判断时 `relation_status` MUST 为 `pending`。

#### Scenario: 关系判断完成落库

- **WHEN** 关系判断步骤完成
- **THEN** 每条候选的关系状态、目标 Entry、判断理由和修订草稿被持久化

### Requirement: 四种关系建议判定与降级

系统 MUST 将候选与已有 Entry 的关系判定为 `new`、`duplicate`、`supplement` 或 `conflict`；`duplicate` 与 `supplement` MUST 指向有效目标 Entry；`supplement` MUST 携带修订草稿；目标 Entry 非法或缺少修订草稿时 MUST 降级为 `new` 或 `duplicate`。

#### Scenario: 无相关 Entry 建议新建

- **WHEN** 候选与项目内已有 Entry 无足够相关关系
- **THEN** 该候选关系状态为 `new`

#### Scenario: 同一知识无新增内容

- **WHEN** 候选与目标 Entry 表述同一知识且不新增实质内容
- **THEN** 该候选关系状态为 `duplicate`，并指向目标 Entry

#### Scenario: 有新增或更新内容

- **WHEN** 候选与目标 Entry 相关且带来新增或更新信息
- **THEN** 该候选关系状态为 `supplement`，指向目标 Entry，并携带修订草稿

#### Scenario: 存在矛盾或判断不清

- **WHEN** 候选与已有 Entry 存在矛盾，或重复与补充难以区分但风险明显
- **THEN** 该候选关系状态为 `conflict`，并进入精审

#### Scenario: 目标 Entry 非法降级新建

- **WHEN** 关系建议为 `duplicate`、`supplement` 或 `conflict`，但目标 Entry 不存在或不属于当前项目
- **THEN** 系统将关系状态降级为 `new`

#### Scenario: 缺少修订草稿降级补充来源

- **WHEN** 关系建议为 `supplement` 但未携带有效修订草稿
- **THEN** 系统将关系状态降级为 `duplicate`

### Requirement: 疑似重复补充来源证据

系统 MUST 支持用户在疑似重复时，把候选的来源证据补充到已有 Entry；补充后候选 MUST 变为已采纳并关联目标 Entry，且 MUST NOT 创建新 Entry。

#### Scenario: 补充来源成功

- **WHEN** 用户确认把疑似重复候选补充到目标 Entry
- **THEN** 候选的证据引用被写入目标 Entry 的来源证据，候选变为已采纳并关联目标 Entry

#### Scenario: 目标 Entry 越权不可补充

- **WHEN** 目标 Entry 不属于候选所属项目或当前 Workspace
- **THEN** 请求失败，不修改任何数据

### Requirement: 可以补充生成并应用修订草稿

系统 MUST 在可以补充时生成 Entry 修订草稿，并在用户确认后把草稿应用到目标 Entry；应用 MUST 同时补充候选来源证据并锁定候选，且 MUST NOT 破坏目标 Entry 的现有来源关系。

#### Scenario: 应用修订草稿

- **WHEN** 用户确认应用修订草稿
- **THEN** 目标 Entry 按草稿更新字段，候选来源证据被补充到目标 Entry，候选变为已采纳并关联目标 Entry

#### Scenario: 未确认不应用

- **WHEN** 用户未确认应用修订草稿
- **THEN** 目标 Entry 保持不变

### Requirement: 可能冲突进入精审

系统 MUST 将可能冲突的候选排除在批量快审之外并进入精审；精审 MUST 提供并列保留、修订和忽略三种处理。

#### Scenario: 冲突候选不参与快审

- **WHEN** 候选关系状态为 `conflict`
- **THEN** 该候选不参与批量快审，进入精审

#### Scenario: 并列保留

- **WHEN** 用户对冲突候选选择并列保留
- **THEN** 系统按新知识创建 Entry，候选变为已采纳

#### Scenario: 修订现有 Entry

- **WHEN** 用户对冲突候选选择修订现有 Entry
- **THEN** 系统把修订草稿应用到目标 Entry，候选变为已采纳并关联目标 Entry

#### Scenario: 忽略冲突候选

- **WHEN** 用户对冲突候选选择忽略
- **THEN** 候选变为已拒绝
