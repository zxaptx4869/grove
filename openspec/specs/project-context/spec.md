# project-context Specification

## Purpose
TBD - created by archiving change add-project-context-snapshot. Update Purpose after archive.
## Requirements
### Requirement: Project Context 归属与 Workspace 隔离
系统 MUST 提供 `ProjectContext` 模型并归属一个 Project；每个 Project 至多有一份上下文快照；读取、纠正与重新生成 MUST 校验 Project 属于当前 Workspace，跨 Workspace 的上下文 MUST 不可见。

#### Scenario: 每个项目至多一份快照
- **WHEN** 用户查询某个项目的上下文
- **THEN** 返回该项目唯一的一份快照；尚未生成时按未生成状态返回，不产生第二份记录

#### Scenario: 跨用户上下文不可见
- **WHEN** 用户 B 尝试访问用户 A 的项目上下文（通过项目 ID）
- **THEN** 请求失败（404），不暴露项目或上下文信息

### Requirement: 初始概要生成
系统 MUST 基于实时项目说明、正式目录节点与已确认 Entry 摘要生成初始概要，至少包含项目概要、当前关注方向与目录主题，并记录生命周期状态与生成时间；目录主题 MUST 取项目顶级目录节点，不枚举全部叶子节点；生成输入 MUST 只使用实时数据（项目说明、顶级目录节点的名称与截断说明、按顶级节点的 Entry 覆盖计数、已确认 Entry 的确定性摘要、用户纠正），不得使用待确认 Candidate，且每次生成 MUST 重新读取实时数据，不得以旧快照作为输入。

#### Scenario: 生成成功
- **WHEN** 项目拥有说明、正式目录节点与已确认 Entry 且系统触发生成
- **THEN** 快照包含项目概要、当前关注方向、目录主题列表、生命周期状态、生成时间、知识覆盖摘要与近期主题；目录主题列表为项目顶级目录节点名称

#### Scenario: 生成输入来自实时数据
- **WHEN** 系统生成项目概要
- **THEN** 输入来自项目说明、实时目录节点与已确认 Entry 摘要，不使用 Candidate，也不使用旧快照内容

#### Scenario: 目录主题确定性派生

- **WHEN** 系统生成快照
- **THEN** 目录主题由顶级目录节点名称确定性派生，不经过 AI 生成

### Requirement: 异步更新与防抖
系统 MUST 在项目说明或正式目录发生重要变化后异步更新快照；对短时间内的多次变化 MUST 防抖合并为一次更新；更新 MUST NOT 阻塞发起变更的原始请求。

#### Scenario: 目录变化触发更新
- **WHEN** 用户创建、修改、移动、删除或排序目录节点
- **THEN** 系统安排项目上下文刷新，原始目录请求立即返回

#### Scenario: 防抖合并
- **WHEN** 短时间内连续发生多次目录或项目说明变化
- **THEN** 这些变化合并为一次上下文刷新，而不是每次变化都立即生成

### Requirement: 失败回退
生成失败时，若已存在有效快照 MUST 继续保留并返回上一份有效快照；若不存在有效快照 MUST 标记为失败并保留错误信息，用户可重新生成。

#### Scenario: 保留上一份有效快照
- **WHEN** 生成失败且该项目已有有效快照
- **THEN** 查询仍返回上一份有效内容，并附带失败错误信息供展示

#### Scenario: 无快照时失败
- **WHEN** 生成失败且该项目尚无有效快照
- **THEN** 快照状态标记为失败，保留错误信息，用户可重新生成

### Requirement: 展示与纠正
用户 MUST 能查看项目上下文快照；用户 SHALL 能纠正 AI 生成的项目概要与当前关注方向；纠正内容 MUST 作为高优先级约束保留，并在后续重新生成时优先考虑；目录主题超过展示上限时 SHALL 折叠显示并提示剩余数量。

#### Scenario: 查看快照
- **WHEN** 用户打开项目上下文
- **THEN** 展示项目说明、项目概要、当前关注方向、目录主题、生命周期状态与生成时间；目录主题超过展示上限时只显示前若干个并提示剩余数量

#### Scenario: 纠正保留为高优先级约束
- **WHEN** 用户纠正项目概要或当前关注方向后重新生成
- **THEN** 纠正内容被持久化，并作为重新生成时的高优先级约束

### Requirement: Agent 公共上下文接口
系统 MUST 提供获取项目上下文的公共接口，供后续 Agent 共享同一份上下文；接口 MUST 返回结构化快照，AI 项目理解 MUST 可自动刷新且可见、可纠正；用户项目说明 MUST 始终具有最高优先级。

#### Scenario: 公共上下文接口返回结构化快照
- **WHEN** 服务端调用项目上下文公共接口
- **THEN** 返回包含项目说明、项目概要、当前关注方向、目录主题、生命周期状态与生成时间的结构化对象

#### Scenario: 用户项目说明优先
- **WHEN** AI 生成的项目概要发生刷新
- **THEN** 用户项目说明原文不被 AI 生成内容覆盖，并作为生成的最高优先级输入

### Requirement: 知识覆盖摘要
系统 MUST 在生成快照时确定性聚合项目内已确认 Entry，生成 `entries_summary`：包含 Entry 总数、四种主类型计数、按顶级目录节点的 Entry 数（直接 + 子树）与最近 20 条 Entry 的标题、节点名与更新时间；该字段 MUST 由服务层计算，不经 AI。

#### Scenario: 生成时写入知识覆盖摘要
- **WHEN** 系统生成快照且项目内有已确认 Entry
- **THEN** `entries_summary` 包含总数、类型分布、顶级节点覆盖数与最近 20 条 Entry 摘要

#### Scenario: 最近条目封顶
- **WHEN** 项目内已确认 Entry 超过 20 条
- **THEN** `entries_summary` 的近期条目只保留最近 20 条

### Requirement: 近期主题提炼
系统 MUST 基于最近已确认 Entry 与顶级目录节点，由生成器提炼 3–5 个近期主题并写入 `recent_themes`；近期主题 MUST 是派生建议，不得改变任何正式 Entry 数据。

#### Scenario: 有近期知识时提炼主题
- **WHEN** 项目内有已确认 Entry 且系统生成快照
- **THEN** `recent_themes` 返回 3–5 个基于近期 Entry 提炼的主题

#### Scenario: 无 Entry 时主题为空
- **WHEN** 项目内没有已确认 Entry
- **THEN** `recent_themes` 返回空列表

### Requirement: 快照版本与更新原因
系统 MUST 为 `ProjectContext` 保存 `version` 与 `last_update_reason`；每次成功生成 MUST 让 `version` 递增，生成失败 MUST NOT 递增；`last_update_reason` MUST 记录最近一次触发来源（如 `entry_archived`、`entry_edited`、`directory_changed`、`project_updated`、`manual_refresh`）。

#### Scenario: 成功生成递增版本
- **WHEN** 快照成功生成
- **THEN** `version` 较上一份成功快照 +1，并记录本次触发原因

#### Scenario: 失败不递增版本
- **WHEN** 快照生成失败
- **THEN** `version` 保持不变，保留上一份有效快照

### Requirement: 刷新触发策略
系统 MUST 只在重要变化时安排快照刷新：新建、编辑或移动 Entry，应用修订草稿，目录结构变化，项目说明变化，用户纠正与手动刷新；补充来源证据、浏览、搜索与候选处理 MUST NOT 触发刷新。系统 MUST 使用防抖窗口合并短时间内的多次重要变化，并遵守最小生成间隔；手动刷新 MUST 始终立即生成。

#### Scenario: 重要变化触发刷新
- **WHEN** 用户新建或编辑 Entry，或修改目录/项目说明
- **THEN** 系统安排一次快照刷新

#### Scenario: 补充来源证据不触发
- **WHEN** 用户只为已有 Entry 补充来源证据
- **THEN** 不安排快照刷新

#### Scenario: 防抖合并
- **WHEN** 短时间内连续发生多次重要变化
- **THEN** 这些变化合并为一次刷新，不逐次生成

#### Scenario: 最小生成间隔
- **WHEN** 距上次成功生成不足最小间隔且再次发生重要变化
- **THEN** 刷新时间推迟到上次成功生成之后的最小间隔边界

#### Scenario: 手动刷新立即执行
- **WHEN** 用户手动点击重新生成
- **THEN** 快照立即重新生成，不受防抖与最小间隔限制

### Requirement: 目录主题展示来自实时目录树
前端项目上下文面板的目录主题徽章 MUST 从项目目录树实时派生，不得直接依赖快照中的 `directory_topics` 展示。

#### Scenario: 目录变化后徽章即时更新
- **WHEN** 项目目录结构发生变化但快照尚未重新生成
- **THEN** 前端目录主题徽章仍展示实时目录树中的顶级节点

### Requirement: 生成来源可追溯
系统 MUST 在快照中记录 `provider`（`demo` / `llm` / `offline`）、`model` 与 `is_fallback`；降级生成（无可用密钥或 demo 占位）MUST 标记为降级；前端 MUST 根据来源展示“真实模型 / 离线生成 / 来源未标注”。

#### Scenario: 真实模型生成
- **WHEN** 快照由真实文本模型成功生成
- **THEN** `provider` 为 `llm`、记录模型名，`is_fallback` 为 false

#### Scenario: 离线降级生成
- **WHEN** 无可用密钥或使用 demo 占位生成快照
- **THEN** `provider` 为 `offline` 或 `demo`，`is_fallback` 为 true

#### Scenario: 旧快照来源未标注
- **WHEN** 快照尚未包含生成来源字段
- **THEN** 前端展示“来源未标注”，不冒充真实模型
