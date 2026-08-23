# entry Specification

## Purpose
TBD - created by archiving change add-entry-and-provenance. Update Purpose after archive.
## Requirements
### Requirement: Entry 归属与主目录
系统 MUST 提供 `Entry` 模型并归属一个 Project；Entry MUST 有一个主目录节点，且该节点 MUST 属于同一 Project；跨 Workspace 的 Entry MUST 不可见。

#### Scenario: 创建 Entry
- **WHEN** 用户采纳候选并选择项目内目录节点
- **THEN** 创建 Entry，归属当前项目并指向所选主目录节点

#### Scenario: 拒绝跨项目节点
- **WHEN** 归档时选择的节点不属于当前项目
- **THEN** 请求失败，不创建 Entry

### Requirement: Entry 结构化字段
Entry MUST 包含标题、核心内容、主类型、信息性质、适用条件与补充说明；主类型 MUST 为知识、方法、参数或提醒之一。

#### Scenario: 从候选继承字段
- **WHEN** 候选归档为 Entry
- **THEN** Entry 的标题、核心内容、主类型、信息性质、适用条件与补充说明来自候选

### Requirement: Entry 来源证据
系统 MUST 提供 `EntrySourceEvidence` 记录 Entry 与 Source/Attachment 的证据关系；归档时 MUST 把候选证据引用转换为 Entry 证据。

#### Scenario: 证据可追溯
- **WHEN** 候选归档为 Entry
- **THEN** 每条候选证据引用生成一条 EntrySourceEvidence，包含 source_id、attachment_id 与 quote

### Requirement: 采纳并归档

系统 MUST 在用户选择目录后原子创建 Entry，并把 Candidate 关联到 Entry；当用户确认新增节点时，系统 MUST 在同一事务内先创建或复用节点，再创建 Entry 与证据；归档成功后 Candidate MUST 不再允许重新打开。

#### Scenario: 原子归档

- **WHEN** 用户选择目录并采纳候选
- **THEN** Entry 与证据关系创建成功，Candidate 关联 Entry 并变为已采纳

#### Scenario: 归档后锁定候选

- **WHEN** 候选已归档为 Entry
- **THEN** 该候选不能重新打开为待采纳

#### Scenario: 新增节点并归档原子成功

- **WHEN** 用户在无合适目录时确认“新增节点并归档”
- **THEN** 节点与 Entry 及证据关系在同一事务内创建，Candidate 关联 Entry 并变为已采纳

#### Scenario: 新增节点并归档失败不留半成品

- **WHEN** “新增节点并归档”在创建节点或写入 Entry/证据的任一环节失败
- **THEN** 不留下新节点、Entry 或已变化的 Candidate，候选仍保持待采纳

#### Scenario: 复用同名同父节点

- **WHEN** 用户确认的新节点在目标父节点下已存在同名节点
- **THEN** 系统复用该已有节点归档 Entry，不创建重复节点

### Requirement: Entry 编辑与移动
用户 SHALL 能编辑 Entry 的标题、核心内容、主类型、信息性质、适用条件、补充说明与主目录节点；移动目录 MUST 仅限同一 Project；修改 MUST 更新 `updated_at`。

#### Scenario: 编辑 Entry
- **WHEN** 用户修改 Entry 字段
- **THEN** 修改被持久化且 `updated_at` 更新

#### Scenario: 移动 Entry 目录
- **WHEN** 用户把 Entry 移动到同一项目内的其他节点
- **THEN** Entry 主目录节点更新，来源证据保持不变

### Requirement: Entry 来源标题展示
系统 MUST 在 Entry 证据输出中返回来源标题（`source_title`），其值来自证据所指向 Source 的标题；该字段用于卡片与列表的来源展示，不改变证据关系本身。

#### Scenario: 证据含来源标题
- **WHEN** 用户读取一条 Entry 及其证据
- **THEN** 每条证据返回 `source_id`、`attachment_id`、`quote` 与 `source_title`

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

### Requirement: 归档优先使用用户确认目录

系统 MUST 在批量归档候选时，优先使用候选的用户确认目录节点（`user_node_id`）；未设置时使用候选推荐节点。

#### Scenario: 使用用户确认目录归档

- **WHEN** 候选存在用户确认目录节点
- **THEN** 批量采纳创建 Entry 时使用该节点

#### Scenario: 回退推荐节点

- **WHEN** 候选不存在用户确认目录节点
- **THEN** 批量采纳使用候选推荐节点

### Requirement: Entry 按项目读取
系统 MUST 支持读取某项目全部已确认 Entry，结果 MUST 按创建时间倒序返回；读取 MUST 校验项目属于当前 Workspace。

#### Scenario: 返回项目全部 Entry
- **WHEN** 用户读取某项目的全部 Entry
- **THEN** 返回该项目全部已确认 Entry，按创建时间倒序

#### Scenario: 越权项目不可见
- **WHEN** 用户请求读取不属于当前 Workspace 项目的全部 Entry
- **THEN** 请求失败（404），不暴露数据

### Requirement: Entry 基础版本历史

系统 MUST 为每条 Entry 维护基础版本历史：创建 Entry 时生成版本 1；每次修改（人工编辑字段或移动目录、应用候选修订草稿、应用 AI 修订建议、从历史恢复）MUST 追加一个版本快照；版本快照 MUST 记录标题、核心内容、主类型、信息性质、适用条件、补充说明与主目录节点；来源证据的增删 MUST NOT 产生版本；每个 Entry 只保留最近 N 条版本（N 默认 10），超出 MUST 滚动丢弃最旧版本。

#### Scenario: 创建生成初始版本
- **WHEN** 用户归档候选创建 Entry
- **THEN** 系统为 Entry 生成版本 1，快照为该 Entry 的初始字段

#### Scenario: 编辑追加快照
- **WHEN** 用户编辑 Entry 字段或移动主目录节点
- **THEN** 系统追加一个版本快照，内容为修改后的字段与主目录节点

#### Scenario: 无实际变化不追加
- **WHEN** 用户提交的编辑没有改变任何字段或主目录节点
- **THEN** 系统不产生新版本

#### Scenario: 应用修订追加版本
- **WHEN** 用户应用候选修订草稿或 AI 修订建议
- **THEN** 系统追加一个版本快照，并记录变更类型与变更说明

#### Scenario: 证据变更不产生版本
- **WHEN** 用户为 Entry 补充来源证据
- **THEN** Entry 字段不变，且不产生新版本

#### Scenario: 超出保留上限滚动丢弃
- **WHEN** Entry 的版本数超过保留上限 N
- **THEN** 系统丢弃最旧版本，只保留最近 N 条

### Requirement: 版本查看与恢复

系统 MUST 提供 Entry 版本列表读取，返回每个保留版本的完整快照字段（含字段值、主目录节点、变更类型、变更说明与创建时间）；读取 MUST 校验 Entry 属于当前 Workspace；用户 SHALL 能把 Entry 恢复到任一保留版本；恢复 MUST 把字段与主目录节点恢复为该版本快照、追加一条「恢复」类型版本，并 MUST NOT 删除后续历史；恢复后 Entry 的 `updated_at` MUST 更新。

#### Scenario: 版本列表按版本号倒序
- **WHEN** 用户读取某 Entry 的版本列表
- **THEN** 返回该 Entry 全部保留版本，按版本号从新到旧排序，每条包含完整快照字段

#### Scenario: 恢复到旧版本
- **WHEN** 用户把 Entry 恢复到某个保留版本
- **THEN** Entry 的字段与主目录节点恢复为该版本快照，并追加一条「恢复」版本，后续历史保持不变

#### Scenario: 越权 Entry 404
- **WHEN** 用户请求的 Entry 不属于当前 Workspace
- **THEN** 请求失败（404），不暴露任何版本数据

#### Scenario: 恢复超出保留范围的版本失败
- **WHEN** 用户请求恢复的版本已被滚动丢弃或不存在
- **THEN** 请求失败（404），Entry 保持不变

### Requirement: AI 修订建议生成与对话调整

系统 MUST 支持用户对单条 Entry 发起 AI 修订建议：生成 MUST 基于该 Entry 的内容与其来源证据，并可结合 AI 自身知识（外部知识）进行求证与补充；AI 输出 MUST 区分「材料/知识库内容」与「AI 知识补充」（回复中以文字标注、草稿以 `external_supplemented` 标记），MUST NOT 编造来源证据；AI 输出 MUST 始终作为候选草稿展示，MUST NOT 直接修改 Entry；对话调整 MUST 是一次性的：每次「继续调整」MUST 携带完整对话历史、当前草稿与用户新指令，且系统 MUST NOT 持久化会话与消息；对话 MUST 区分讨论与提出草稿——用户提问、求证、讨论、质疑时 MUST 只返回文字回复且不产生或更新草稿，只有用户明确要求修改时 MUST 返回草稿，且该选择 MUST 通过显式意图（`intent: discuss | propose`）结构化表达并在响应中返回；模型不可用或调用失败时 MUST 明确标记降级（`is_fallback` 与原因），不得静默降级。

#### Scenario: 发起修订建议
- **WHEN** 用户对某 Entry 点击「AI 修订建议」并生成
- **THEN** 返回候选草稿（含建议字段、修订原因与变更说明），Entry 本身保持不变

#### Scenario: 继续对话调整
- **WHEN** 用户在对话中发送新指令
- **THEN** 模型基于完整对话历史、当前草稿与新指令返回更新后的草稿与自然语言回复

#### Scenario: 结合外部知识补充且可辨识
- **WHEN** 用户要求求证或丰富，且知识库证据不足
- **THEN** AI 可结合自身知识补充，并在回复中文字标注「AI 知识补充」、草稿标记 `external_supplemented=true`，不编造来源证据

#### Scenario: 纯讨论只回复不产草稿
- **WHEN** 用户发送提问、求证、讨论或质疑的消息
- **THEN** 响应 `intent=discuss`，只返回文字回复，不产生也不更新草稿；若已有草稿则保持不变

#### Scenario: 明确要求修改才更新草稿
- **WHEN** 用户明确要求修改（补充、精简、改写法、加条件等）
- **THEN** 响应 `intent=propose` 并返回更新后的完整草稿

#### Scenario: 意图与草稿不一致时归一化
- **WHEN** 模型输出 `intent=discuss` 却携带草稿，或 `intent=propose` 却缺少草稿
- **THEN** 应用层按 `discuss` 处理并记录告警日志，不更新草稿

#### Scenario: 关闭面板即消失
- **WHEN** 用户关闭修订建议面板且未应用
- **THEN** 对话与草稿不落库，Entry 保持不变

#### Scenario: 模型不可用降级可见
- **WHEN** 未配置文本模型密钥或模型调用失败
- **THEN** 响应标记 `is_fallback=true` 并返回降级原因，不生成草稿，且记录告警日志

### Requirement: 应用 AI 修订建议

系统 MUST 支持用户在确认后应用 AI 修订草稿：应用 MUST 按用户确认后的字段更新 Entry、创建「AI 修订建议」虚拟 Source（记录用户指令、AI 输出与 provider/model）并加入 Entry 来源证据、追加一条 `ai_revision` 类型版本并记录变更说明；原有来源证据 MUST 保持不变；未应用时 Entry MUST 保持不变；越权 Entry MUST 请求失败（404）。

#### Scenario: 应用草稿成功并沉淀虚拟来源
- **WHEN** 用户确认并应用 AI 修订草稿
- **THEN** Entry 按确认后的字段更新，来源证据新增「AI 修订建议」虚拟 Source（可打开查看指令与 AI 输出），并追加 `ai_revision` 版本带变更说明，原有来源证据不变

#### Scenario: 未应用保持不变
- **WHEN** 用户放弃或关闭修订建议面板
- **THEN** Entry 内容、来源与版本均不发生变化

#### Scenario: 越权 Entry 不可应用
- **WHEN** 应用请求的 Entry 不属于当前 Workspace
- **THEN** 请求失败（404），不修改任何数据
