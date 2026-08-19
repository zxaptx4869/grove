# directory-drafting Specification

## Purpose
TBD - created by archiving change add-directory-agent-drafting. Update Purpose after archive.
## Requirements
### Requirement: Directory Draft 归属与活跃草稿
系统 MUST 提供 `DirectoryDraft` 模型并归属一个 Project，每个 Project 至多有一份活跃草稿；草稿与草稿节点 MUST 按 Workspace/Project 隔离，跨 Workspace 读取 MUST 失败；草稿 MUST 包含状态机（`drafting` / `awaiting_input` / `pending_confirm` / `confirmed` / `discarded`）与下一步动作（`clarify` / `generate`）。

#### Scenario: 每项目至多一份活跃草稿
- **WHEN** 用户为项目创建目录草稿且已存在活跃草稿
- **THEN** 复用或覆盖现有草稿，不产生第二份活跃草稿

#### Scenario: 跨项目草稿不可见
- **WHEN** 用户访问不属于当前 Workspace 或项目的草稿
- **THEN** 请求失败（404），不暴露草稿内容

### Requirement: 问卷式澄清
系统 MUST 支持 Directory Agent 一次返回 3–5 道结构化澄清问题，每道包含 id、问题文本、选项列表与是否多选；用户 MUST 能一次提交全部答案，每道题可点选选项或自由输入；澄清批次 MUST 上限为 2 次，达到上限后 MUST 直接生成候选树。

#### Scenario: 一次返回多道问题
- **WHEN** Agent 判定需要澄清
- **THEN** 一次返回 3–5 道带选项的问题，不逐题轮询

#### Scenario: 选项与自由输入
- **WHEN** 用户提交澄清答案
- **THEN** 每道题可以选选项，也可以输入自由文本；多选问题接受答案数组

#### Scenario: 澄清批次上限
- **WHEN** 澄清答案提交后 Agent 仍判定信息不足且已使用 2 次澄清批次
- **THEN** Agent 不再提问，直接生成候选树

### Requirement: 候选树生成
系统 MUST 基于项目说明、Project Context 快照与用户澄清答案生成候选目录树；候选树 MUST 只写入草稿，不得直接创建或修改正式节点；无可用密钥时 MUST 以确定性兜底生成候选树，并标记生成来源。

#### Scenario: 生成候选树
- **WHEN** 用户提交澄清答案或无需澄清
- **THEN** 草稿进入待确认状态，包含层级化候选节点（名称、说明、父引用与顺序）

#### Scenario: 生成不触碰正式目录
- **WHEN** 候选树生成完成
- **THEN** 正式节点表无任何变化，AI 输出只存在于草稿

### Requirement: 可视化与内联编辑
系统 MUST 提供可视化候选树，默认以展示态呈现，每个节点带“是否采用”复选框且默认选中；用户 MUST 点击编辑按钮后才进入编辑态，可新增子节点、重命名、更新说明与删除节点；编辑 MUST 只修改草稿，不影响正式目录；确认应用 MUST 只创建被采用的节点，未采用节点及其子树不创建。

#### Scenario: 内联编辑草稿
- **WHEN** 用户在候选树中新增、改名、改说明或删除草稿节点
- **THEN** 草稿节点更新并持久化，正式目录不变

#### Scenario: 默认展示与勾选采用
- **WHEN** 用户查看候选树
- **THEN** 节点默认展示名称与说明，复选框默认选中；点击编辑按钮才进入输入态

#### Scenario: 未采用节点不创建
- **WHEN** 用户取消勾选某节点并确认应用
- **THEN** 该节点及其子树不作为正式节点创建

#### Scenario: 待确认状态可编辑
- **WHEN** 草稿处于待确认状态
- **THEN** 用户仍可编辑草稿节点后再应用

### Requirement: 确认应用
系统 MUST 在用户确认后校验并原子应用草稿：parent 引用合法、无环、名称长度合法、节点总数不超过上限；任一校验失败 MUST 不创建任何节点；成功后 MUST 创建全部正式节点、标记草稿为 `confirmed`，并触发项目上下文刷新。

#### Scenario: 原子应用成功
- **WHEN** 用户确认应用候选树
- **THEN** 全部草稿节点按树结构与顺序创建为正式节点，草稿标记为已确认

#### Scenario: 校验失败不留半成品
- **WHEN** 候选树存在非法父引用、环、超长名称或超节点上限
- **THEN** 请求失败，正式目录不变，草稿保持待确认

#### Scenario: 应用后触发上下文刷新
- **WHEN** 草稿应用成功创建目录节点
- **THEN** 系统安排项目上下文刷新

### Requirement: 生成来源可追溯
系统 MUST 在草稿中记录 `provider`（`demo` / `llm` / `offline`）、`model` 与 `is_fallback`；降级生成 MUST 标记为降级，禁止静默降级。

#### Scenario: 记录生成来源
- **WHEN** 候选树或澄清问题由 Agent 生成
- **THEN** 草稿记录 provider、model 与降级标记

### Requirement: 目录共创入口
空目录知识空间内容区的「与 AI 共创目录」入口 MUST 发起目录起草流程，而不是占位提示；项目已有正式目录节点时，项目首页与知识空间页头 MUST NOT 显示「与 AI 共创目录」入口。

#### Scenario: 空目录入口发起起草
- **WHEN** 用户在空目录内容区点击「与 AI 共创目录」
- **THEN** 打开目录起草工作区并创建或复用活跃草稿

#### Scenario: 非空目录不显示入口
- **WHEN** 项目已有正式目录节点
- **THEN** 项目首页与知识空间页头不显示「与 AI 共创目录」入口，避免与“从零起草仅适用空目录”冲突

### Requirement: 对话调整草稿
系统 MUST 在候选树生成后（`pending_confirm`）开放对话调整：用户发送消息，系统 MUST 把当前会话全部消息与候选树交给 Directory Agent；Agent 返回回复文字与可选的新候选树，返回树时 MUST 自动替换草稿节点并提示应用节点数；会话轮数 MUST 上限为 30，超限 MUST 拒绝并提示重新起草。

#### Scenario: 对话调整候选树
- **WHEN** 用户在待确认草稿中发送“把施工节点拆细”等消息
- **THEN** 系统追加用户消息，Agent 回复文字，并在返回新树时自动替换草稿节点

#### Scenario: 纯讨论不改树
- **WHEN** Agent 只返回回复文字而不返回新树
- **THEN** 草稿节点保持不变，仅追加助手回复

#### Scenario: 会话轮数上限
- **WHEN** 草稿会话轮数达到 30
- **THEN** 后续消息被拒绝，提示重新起草

#### Scenario: 对话只在待确认状态开放
- **WHEN** 草稿处于澄清阶段或其他状态
- **THEN** 对话消息接口返回冲突，不追加消息

### Requirement: 共创工作区布局
目录共创工作区 MUST 以“候选树在左、对话区在右”的双栏布局展示候选树与对话消息。

#### Scenario: 双栏布局
- **WHEN** 用户打开候选树与对话
- **THEN** 左侧展示候选树（可内联编辑），右侧展示对话消息与输入框
