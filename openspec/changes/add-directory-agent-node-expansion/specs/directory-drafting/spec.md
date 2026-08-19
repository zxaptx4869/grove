## MODIFIED Requirements

### Requirement: Directory Draft 归属与活跃草稿
系统 MUST 提供 `DirectoryDraft` 模型并归属一个 Project，每个 Project 至多有一份活跃草稿；草稿与草稿节点 MUST 按 Workspace/Project 隔离，跨 Workspace 读取 MUST 失败；草稿 MUST 包含 `kind`（`draft` 从零起草 / `expand` 节点拓展）与可选 `target_node_id`（仅 `expand` 使用，指向正式节点）；草稿 MUST 包含状态机（`drafting` / `awaiting_input` / `pending_confirm` / `confirmed` / `discarded`）与下一步动作（`clarify` / `generate`）。

#### Scenario: 每项目至多一份活跃草稿
- **WHEN** 用户为项目创建目录草稿且已存在活跃草稿
- **THEN** 复用或覆盖现有草稿，不产生第二份活跃草稿

#### Scenario: 跨项目草稿不可见
- **WHEN** 用户访问不属于当前 Workspace 或项目的草稿
- **THEN** 请求失败（404），不暴露草稿内容

#### Scenario: expand 草稿记录目标节点
- **WHEN** 用户对某正式节点发起拓展
- **THEN** 草稿 `kind` 为 `expand` 且 `target_node_id` 指向该节点

#### Scenario: 覆盖重开 expand 草稿
- **WHEN** 用户确认覆盖现有活跃草稿并发起另一节点的拓展
- **THEN** 同一草稿重置为 `kind=expand`、指向新目标节点，清空节点与消息、清零轮数与澄清批次

### Requirement: 确认应用
系统 MUST 在用户确认后按草稿 `kind` 分流应用：`draft` 仅允许空目录项目，校验 parent 引用合法、无环、名称长度合法、节点总数不超过上限后原子创建全部被采用节点；`expand` 校验目标节点存在且属于项目、草稿树合法、勾选的移除项均为未阻断的建议移除后，单事务创建勾选的新增节点并删除勾选的建议移除子树。任一校验失败 MUST 不产生任何正式节点变更；成功后 MUST 标记草稿为 `confirmed` 并触发项目上下文刷新。

#### Scenario: 原子应用成功（draft）
- **WHEN** 用户确认应用从零起草的候选树
- **THEN** 全部草稿节点按树结构与顺序创建为正式节点，草稿标记为已确认

#### Scenario: expand 应用新增与移除
- **WHEN** 用户确认应用节点拓展草稿
- **THEN** 勾选的新增节点创建为目标节点的子节点，勾选的建议移除子树被删除，其余节点保留

#### Scenario: 校验失败不留半成品
- **WHEN** 草稿存在非法父引用、环、超长名称、超节点上限或勾选受保护移除项
- **THEN** 请求失败，正式目录不变，草稿保持待确认

#### Scenario: 应用后触发上下文刷新
- **WHEN** 草稿应用成功创建或删除目录节点
- **THEN** 系统安排项目上下文刷新

### Requirement: 对话调整草稿
系统 MUST 在候选树生成后（`pending_confirm`）开放对话调整：用户发送消息，系统 MUST 把当前会话全部消息与当前草稿树交给 Directory Agent；`draft` 草稿的草稿树为完整候选树，`expand` 草稿的草稿树为目标节点下的完整目标子树；Agent 返回回复文字与可选新树，返回树时 MUST 自动替换草稿节点并提示应用节点数；会话轮数 MUST 上限为 30，超限 MUST 拒绝并提示重新起草。

#### Scenario: 对话调整候选树
- **WHEN** 用户在待确认草稿中发送“把施工节点拆细”等消息
- **THEN** 系统追加用户消息，Agent 回复文字，并在返回新树时自动替换草稿节点

#### Scenario: expand 对话应用目标子树
- **WHEN** 用户在节点拓展草稿中发送调整消息
- **THEN** Agent 返回更新后的完整目标子树并替换草稿，差异快照随之刷新

#### Scenario: 纯讨论不改树
- **WHEN** Agent 只返回回复文字而不返回新树
- **THEN** 草稿节点保持不变，仅追加助手回复

#### Scenario: 会话轮数上限
- **WHEN** 草稿会话轮数达到 30
- **THEN** 后续消息被拒绝，提示重新起草

#### Scenario: 对话只在待确认状态开放
- **WHEN** 草稿处于澄清阶段或其他状态
- **THEN** 对话消息接口返回冲突，不追加消息
