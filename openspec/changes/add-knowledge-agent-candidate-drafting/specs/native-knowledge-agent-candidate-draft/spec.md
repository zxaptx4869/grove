## ADDED Requirements

### Requirement: 原生回答只在可整理时显示动作
原生 App MUST 只在 completed / partial 且含有效 citations 的回答卡中显示「整理成知识」，并将其表达为结构化后续动作而非正式知识状态；insufficient、failed、clarification、cancelled 和无引用回答 MUST NOT 提供可执行入口。

#### Scenario: 有证据回答显示入口
- **WHEN** 回答有可用 citation 且状态为 completed 或 partial
- **THEN** 回答卡在引用与范围信息之后显示「整理成知识」动作，并有可理解的辅助名称

#### Scenario: 不可整理回答隐藏入口
- **WHEN** 回答无有效 citation 或处于知识不足、失败、澄清、取消状态
- **THEN** 界面不显示会创建 Draft 的入口，也不使用禁用按钮暗示仍可保存

### Requirement: Workspace 回答先确认目标项目
原生 App MUST 在项目范围回答中使用固化项目，在 Workspace 回答命中多个项目时先显示目标项目 Sheet；Sheet 只列出服务端返回的可用项目，不展示目录节点，用户取消时不提交 operation Run。

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
原生 App MUST 把显式整理请求显示为用户消息，把 operation Run 的 preparing/generating/verifying 等有限阶段显示为可核验过程，并从服务端 Message Page / Draft 集合恢复 generating、draft、failed、cancelled、confirmed 状态；MUST NOT 展示隐藏推理或只依赖本地临时状态。

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
原生 App MUST 使用结构化草稿卡展示目标项目、`AI 草稿 · 未创建候选`、标题、内容、类型建议与来源摘要；用户可在原生可滚动 Sheet 编辑允许字段。Draft、即时回答和正式 Entry MUST 使用不同文案与状态表达。

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
原生 App MUST 在确认 Sheet 中显示目标项目、将创建一个待确认 Candidate、保留来源且不会直接写入正式知识；主按钮 MUST 使用「创建待确认知识」或等价明确文案。确认中禁止重复提交，未知结果重试 MUST 复用 client_operation_id。

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
原生 App MUST 在确认成功后显示持久化回执，包含目标项目、Candidate 待确认状态、来源保留和可追溯的创建时间/标识；回执 MUST 明确“尚未写入正式知识”。移动确认台尚未接入时 MUST NOT 提供伪造的可用跳转。

#### Scenario: Candidate 创建成功
- **WHEN** 确认接口返回 confirmed Draft 与 Candidate
- **THEN** thread 将草稿卡收敛为「已创建待确认知识」回执，并在历史恢复时保持一致

#### Scenario: 辅助建议仍在处理或失败
- **WHEN** Candidate 已创建但目录/关系建议为 pending 或受影响
- **THEN** 回执显示真实状态与后续将在确认流程处理，不把 Candidate 标为正式或完全归档

### Requirement: 候选草稿界面严格对齐移动原型基线
原生 App MUST 按 `grove-mobile-agent-prototype.html` 的 Agent 标签、卡片密度、Badge、字段层级、Sheet、按钮和回执视觉基线实现本 change 范围，并使用正式 React Native 组件与 Grove 主题重新构建；有意裁剪 MUST 与 design 一致。360×800、390×844、412×915 下不得出现横向溢出、固定层遮挡或不可达操作。

#### Scenario: 三视口草稿路径
- **WHEN** 分别在 360×800、390×844、412×915 走查项目选择、生成、草稿、编辑、确认、回执和失败重试
- **THEN** 信息层级与原型一致，长标题/正文正确换行，顶栏、Composer、底栏、Sheet、安全区与系统键盘互不遮挡

#### Scenario: 读屏与触控操作
- **WHEN** 用户通过辅助技术操作整理入口、项目选择、编辑字段、确认、关闭和重试
- **THEN** 控件具备可理解名称/状态/顺序，主要触控目标不小于 44×44 且状态不只依赖颜色

