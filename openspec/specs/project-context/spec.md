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
系统 MUST 基于项目说明与正式目录节点生成初始概要，至少包含项目概要、当前关注方向与目录主题，并记录生命周期状态与生成时间；生成输入 MUST 只使用项目说明与正式目录节点，不得使用待确认 Candidate 或尚未实现的已确认 Entry。

#### Scenario: 生成成功
- **WHEN** 项目拥有说明与正式目录节点且系统触发生成
- **THEN** 快照包含项目概要、当前关注方向、目录主题列表、生命周期状态与生成时间

#### Scenario: 生成只使用项目说明与正式目录
- **WHEN** 系统生成项目概要
- **THEN** 输入仅来自项目说明与正式目录节点，不使用 Candidate 或 Entry

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
用户 MUST 能查看项目上下文快照；用户 SHALL 能纠正 AI 生成的项目概要与当前关注方向；纠正内容 MUST 作为高优先级约束保留，并在后续重新生成时优先考虑。

#### Scenario: 查看快照
- **WHEN** 用户打开项目上下文
- **THEN** 展示项目说明、项目概要、当前关注方向、目录主题、生命周期状态与生成时间

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

