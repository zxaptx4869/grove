## REMOVED Requirements

### Requirement: 原生回答只在可整理时显示动作
**Reason**: 原生端不再提供固定“整理成知识”入口。

**Migration**: dialogue candidate 块只显示为未应用建议；共享后端 Candidate Draft 能力保留。


#### Scenario: 有证据回答显示入口
- **WHEN** 回答有可用 citation 且状态为 completed 或 partial
- **THEN** 回答卡在引用与范围信息之后显示「整理成知识」动作，并有可理解的辅助名称

#### Scenario: 不可整理回答隐藏入口
- **WHEN** 回答无有效 citation 或处于知识不足、失败、澄清、取消状态
- **THEN** 界面不显示会创建 Draft 的入口，也不使用禁用按钮暗示仍可保存
### Requirement: Workspace 回答先确认目标项目
**Reason**: 原生端不再发起持久 Candidate Draft，因此不再选择写入项目。

**Migration**: 无数据迁移；现有测试数据保留在数据库。


#### Scenario: 项目范围直接开始
- **WHEN** 用户在项目范围回答点击整理
- **THEN** App 以该项目和 source_run_id 提交可见操作消息，不再弹出目录或项目选择

#### Scenario: 多项目回答选择目标
- **WHEN** Workspace 回答的有效 citations 来自多个项目
- **THEN** App 打开项目选择 Sheet，解释草稿只采用所选项目的证据，选择后才提交

#### Scenario: 取消项目选择
- **WHEN** 用户关闭目标项目 Sheet
- **THEN** 对话、Run 与知识数据保持不变
### Requirement: 草稿生成与历史恢复在对话中可见
**Reason**: 原生当前正式历史只恢复 Conversation、Message、Run 与 dialogue 快照，不恢复旧草稿交互。

**Migration**: 不删除共享 Draft 数据或接口；其他调用方不受影响。


#### Scenario: 提交整理动作
- **WHEN** 用户确认目标项目并发起整理
- **THEN** thread 显示可见用户操作消息和生成过程，重复点击不会产生第二个本地 Run

#### Scenario: 后台与重启恢复
- **WHEN** App 在生成中进入后台或被关闭后重新打开
- **THEN** 后台停止轮询，回到前台或重启后从服务端恢复同一 Draft 与 Run

#### Scenario: 草稿生成失败
- **WHEN** operation Run 失败或降级无法形成有效草稿
- **THEN** 对话内保留错误与重试入口，不创建成功草稿卡或 Candidate 回执
### Requirement: 草稿卡和编辑 Sheet 区分 AI 建议
**Reason**: 原生端移除持久草稿编辑流程。

**Migration**: 普通对话 candidate 块以只读候选语义展示。


#### Scenario: 查看生成草稿
- **WHEN** Draft 进入 draft 状态
- **THEN** thread 显示草稿卡、目标项目、来源数量和「编辑并检查」主动作，不宣称已归档

#### Scenario: 编辑长内容
- **WHEN** 用户在 360×800 设备打开含长正文的编辑 Sheet 并唤起系统键盘
- **THEN** 标题、正文、类型与底部动作可滚动可达，键盘和安全区不遮挡当前输入或确认按钮

#### Scenario: 取消编辑
- **WHEN** 用户关闭编辑 Sheet 且未提交修改
- **THEN** 服务端 Draft 不变，焦点返回草稿卡且对话滚动位置稳定
### Requirement: 创建 Candidate 前再次明确后果
**Reason**: 原生端不再调用 Candidate 创建写接口。

**Migration**: 共享后端确认服务及其幂等边界保持不变。


#### Scenario: 查看确认说明
- **WHEN** 用户从 Draft 卡进入确认
- **THEN** Sheet 明确展示编辑后的标题、目标项目、来源数量和“尚未成为正式知识”

#### Scenario: 确认请求进行中
- **WHEN** 创建请求尚未返回
- **THEN** 主按钮显示进行中并禁用重复点击，关闭/返回行为不会伪造成功

#### Scenario: 网络结果未知后重试
- **WHEN** 请求超时且客户端不知道服务端是否已创建 Candidate
- **THEN** 界面保留 Draft 和重试入口，并使用原 client_operation_id 恢复同一结果
### Requirement: 成功回执只表达待确认 Candidate
**Reason**: 原生端不再产生 Candidate 回执或桌面确认台交接。

**Migration**: 已有数据库测试记录不删除，不要求原生端交互兼容。


#### Scenario: Candidate 创建成功
- **WHEN** 确认接口返回 confirmed Draft 与 Candidate
- **THEN** thread 将草稿卡收敛为「已创建待确认知识」回执，并在历史恢复时保持一致

#### Scenario: 辅助建议仍在处理或失败
- **WHEN** Candidate 已创建但目录/关系建议为 pending 或受影响
- **THEN** 回执显示真实状态与后续将在确认流程处理，不把 Candidate 标为正式或完全归档
### Requirement: 候选草稿界面严格对齐移动原型基线
**Reason**: 对应原生业务界面整体移除。

**Migration**: 保留仍被对话使用的共享主题和基础 UI，不保留废弃业务组件副本。


#### Scenario: 三视口草稿路径
- **WHEN** 分别在 360×800、390×844、412×915 走查项目选择、生成、草稿、编辑、确认、回执和失败重试
- **THEN** 信息层级与原型一致，长标题/正文正确换行，顶栏、Composer、底栏、Sheet、安全区与系统键盘互不遮挡

#### Scenario: 读屏与触控操作
- **WHEN** 用户通过辅助技术操作整理入口、项目选择、编辑字段、确认、关闭和重试
- **THEN** 控件具备可理解名称/状态/顺序，主要触控目标不小于 44×44 且状态不只依赖颜色

## ADDED Requirements

### Requirement: 原生端候选内容保持只读边界
原生 App MUST 将 dialogue candidate 作为未应用的只读建议展示，不提供固定“整理成知识”、草稿编辑、Candidate 创建或确认写入入口；共享 Candidate 服务与其他端调用方不受影响。

#### Scenario: 展示未应用候选
- **WHEN** 正式 dialogue blocks 包含 candidate 或 candidate_text_only
- **THEN** 移动端标识为 AI 候选/未应用并允许阅读，不显示保存、确认或写入正式知识的操作
