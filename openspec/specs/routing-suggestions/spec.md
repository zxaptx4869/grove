# routing-suggestions Specification

## Purpose
为 Source 推荐项目、为 Candidate 推荐真实目录节点与备选，并落库路由状态供确认台使用。
## Requirements
### Requirement: Source 项目推荐
系统 MUST 在全局收集箱来源处理时为未归属来源生成推荐项目与推荐理由；存在可选项目但模型首次未输出项目推荐时，系统 MUST 重试一次（重试仅补充项目推荐，不覆盖已生成的候选）；推荐明确时 MUST 自动归属该项目；推荐仍不明确时 MUST 保持未归属；已归属项目的来源 MUST 直接使用当前项目，不调用 AI 猜测项目。

#### Scenario: 全局来源推荐项目
- **WHEN** 系统处理一个未归属项目的来源
- **THEN** 生成 `recommended_project_id` 与推荐理由

#### Scenario: 模型漏输出项目推荐时重试
- **WHEN** 未归属来源存在可选项目，但模型首次输出未包含项目推荐
- **THEN** 系统重试一次并要求补充项目推荐；重试得到有效推荐则采用，仍为空则保持未归属

#### Scenario: 推荐不明确保持未归属
- **WHEN** 重试后仍无法判断来源应归属哪个项目
- **THEN** `recommended_project_id` 为空，来源保持未归属

#### Scenario: 推荐明确自动归属项目
- **WHEN** AI 为未归属来源推荐了明确的所属项目
- **THEN** 来源自动归属该项目，并触发其候选的目录推荐

#### Scenario: 项目内来源不猜项目
- **WHEN** 系统处理一个已归属项目的来源
- **THEN** 不生成项目推荐，直接使用该来源当前项目

### Requirement: Candidate 目录推荐
系统 MUST 为每条候选生成真实 `node_id` 的主建议、备选与理由；主建议与备选 MUST 来自当前项目真实存在的节点，不得自由输出无法匹配的路径。

#### Scenario: 主建议为真实节点
- **WHEN** 系统为一条候选计算目录推荐
- **THEN** `recommended_node_id` 指向当前项目内真实存在的节点

#### Scenario: 备选为真实节点
- **WHEN** 系统为候选提供备选目录
- **THEN** 每个备选 `node_id` 均指向当前项目内真实存在的节点

#### Scenario: 拒绝非法节点
- **WHEN** Agent 输出的主建议或备选不是当前项目内的真实节点
- **THEN** 应用层拒绝该推荐，不保存非法 `node_id`

### Requirement: 三档路由状态
系统 MUST 用三档可解释状态表达推荐可信度：推荐明确（`recommended`）、需要确认（`needs_review`）、暂无合适位置（`no_suitable`）；MUST NOT 展示模型自报的伪精确百分比。

#### Scenario: 推荐明确
- **WHEN** AI 对候选目录有明确主建议
- **THEN** `routing_status` 为 `recommended`

#### Scenario: 需要确认
- **WHEN** AI 有建议但不确定
- **THEN** `routing_status` 为 `needs_review`

#### Scenario: 暂无合适位置
- **WHEN** AI 找不到合适目录节点
- **THEN** `routing_status` 为 `no_suitable`

### Requirement: 路由步骤触发与重跑
系统 MUST 在项目内来源处理成功后立即路由；全局来源在自动归属项目后路由；用户修改来源项目后 MUST 重新路由并覆盖旧推荐；重跑 MUST NOT 复制候选或正式知识。

#### Scenario: 项目内来源处理完即路由
- **WHEN** 一个已归属项目的来源处理成功
- **THEN** 系统立即为其候选计算目录推荐

#### Scenario: 全局来源自动归属项目后路由
- **WHEN** AI 为未归属来源推荐并自动归属项目
- **THEN** 系统为该来源候选计算目录推荐

#### Scenario: 修改项目重新路由
- **WHEN** 用户修改一个来源的所属项目
- **THEN** 系统重新计算其候选的目录推荐，并覆盖旧推荐

### Requirement: 无合适位置的新节点建议

当候选目录推荐判定为 `no_suitable` 时，系统 MUST 可为该候选保存一条新节点建议，包含建议名称、可选父节点与理由；建议父节点 MUST 是当前项目内的真实节点或为空（表示根节点）。新节点建议 MUST NOT 被自动创建为正式节点。

#### Scenario: 生成新节点建议

- **WHEN** AI 判定候选暂无合适目录并提出新节点建议
- **THEN** 候选保存新节点建议的名称、父节点与理由，且路由状态为 `no_suitable`

#### Scenario: 拒绝非法父节点

- **WHEN** 新节点建议的父节点不是当前项目内的真实节点
- **THEN** 应用层不保存该父节点，新节点建议按根节点或空建议处理

#### Scenario: 建议仅作候选

- **WHEN** 候选携带新节点建议
- **THEN** 系统不自动创建节点，节点仅在用户明确确认后创建
