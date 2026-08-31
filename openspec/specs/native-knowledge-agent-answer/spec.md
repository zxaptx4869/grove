# native-knowledge-agent-answer Specification

## Purpose
TBD - created by archiving change add-native-knowledge-agent-conversation. Update Purpose after archive.
## Requirements
### Requirement: Run 过程只展示可验证阶段
原生 App MUST 将 Run 的 waiting/processing、`current_step`、实际回答模式和当前轮次映射为准备、理解问题、选择回答方式、检索正式知识、读取 Entry、核验证据、深度查找与综合回答等用户可验证状态；MUST NOT 展示隐藏推理、控制器内部理由或与服务端无关的伪进度动画。

#### Scenario: quick Run 处理中
- **WHEN** quick Run 正在搜索或读取证据
- **THEN** 过程卡显示对应可验证动作和生成时范围，并提供取消，不编造详细思考步骤

#### Scenario: 调查进行到第二轮
- **WHEN** investigate Run 的 `current_round=2` 且仍 processing
- **THEN** 过程卡显示深度查找和当前轮次，不能显示超过服务端预算的虚假总进度

#### Scenario: 步骤未知
- **WHEN** 客户端收到未识别的 future `current_step`
- **THEN** 使用稳定的「正在处理」通用文案且继续轮询，不崩溃或暴露原始枚举

#### Scenario: Run 终态
- **WHEN** Run 进入任一终态
- **THEN** 过程卡转为回答、知识不足、失败或已取消状态，不继续显示「正在处理」

### Requirement: 结构化回答状态清晰区分
原生 App MUST 依据结构化 `answer.status` 展示 completed、partial、insufficient、failed、clarification，并结合而非仅依赖 Run 状态；AI 即时回答 MUST 标识为「基于正式知识」而不是 Candidate 或正式 Entry。

#### Scenario: 正常带引用回答
- **WHEN** answer 为 completed 且有有效 citations
- **THEN** 页面展示回答正文、生成时范围和来源条，并使用「基于正式知识」语义

#### Scenario: 部分回答
- **WHEN** answer 为 partial 且仍有有效内容
- **THEN** 页面保留有效回答和引用，并在内容附近说明哪些部分降级、失效或未覆盖

#### Scenario: 知识不足
- **WHEN** answer.status 为 insufficient，无论 quick Run 是 completed 还是调查 Run 是 partial
- **THEN** 页面统一显示知识不足语义、`insufficient_note` 和可用 gaps，不使用成功完成文案掩盖不足

#### Scenario: 澄清回答
- **WHEN** answer.status 为 clarification
- **THEN** 页面显示需要用户补充的信息并允许在同一对话继续回复，不把它当失败或事实答案

#### Scenario: 回答失败
- **WHEN** answer.status 为 failed 或 Run 为 failed
- **THEN** 页面显示持久错误、已知原因和重新提问操作，不用 toast 代替可恢复状态

### Requirement: 调查摘要有限且可解释
原生 App MUST 对 investigate Run 显示实际模式、完成轮数、查询数、稳定停止原因与未解决缺口；coverage/gaps/conflicts MAY 在用户展开后显示，但 MUST NOT 把过程摘要当作正式事实或宣称已穷尽全部知识。

#### Scenario: 控制器完成调查
- **WHEN** 调查以 `controller_complete` 停止
- **THEN** 回答卡显示实际轮次/查询数和已完成深度查找，不展示仍在搜索

#### Scenario: 达到预算
- **WHEN** 调查以 max_rounds/query_budget/entry_budget/evidence_budget 停止
- **THEN** 页面明确说明在预算边界停止并列出未解决缺口，不写「已查完所有知识」

#### Scenario: 无进展或不足
- **WHEN** stop_reason 为 no_progress 或 insufficient
- **THEN** 页面显示没有发现更多可核验证据或当前知识不足，并保留已有引用

### Requirement: 引用 Sheet 区分回答、Entry 与 Source 原文
原生 App MUST 将当前 Run citation 呈现为可点击来源条；打开后 MUST 显示 Evidence 快照中的 Entry 标题、Source 标题、真实 quote、项目与目录归属，并明确 quote 是本次回答核验的 Source 原文。客户端 MUST NOT 自行生成 quote、把回答正文标成原文或用当前 Entry 覆盖历史 Run 快照。

#### Scenario: 打开项目范围引用
- **WHEN** 用户点击项目范围回答的一条 citation
- **THEN** Bottom Sheet 显示 Entry、目录、Source 与核验原文，并可关闭返回原滚动位置

#### Scenario: 打开 Workspace 范围引用
- **WHEN** 用户点击全部知识范围回答的一条 citation
- **THEN** Sheet 额外明确显示该 Evidence 的项目归属，避免误认为来自当前其他项目

#### Scenario: 历史对象后来变化或删除
- **WHEN** Citation 所指 Entry/Source 当前已变化或删除
- **THEN** Sheet 仍显示 Run 保存的标题/归属/quote 快照；当前对象入口不可用时明确说明，不改写历史回答

#### Scenario: 查看当前 Entry
- **WHEN** 用户从 citation Sheet 打开当前知识且 Entry 仍可访问
- **THEN** 当前 Entry 内容与「本次回答证据快照」分区标注，不能混为同一时点内容

### Requirement: 冲突双方证据可分别核验
原生 App MUST 把结构化冲突与普通不足提示区分，展示冲突摘要、双方 Entry 标题以及双方各自完整 citation；用户 MUST 能分别打开两侧 Source Evidence，系统 MUST NOT 替用户裁决。

#### Scenario: 双方证据有效
- **WHEN** answer.conflicts 包含两个当前 Run citation
- **THEN** 冲突卡并列显示双方观点和独立来源入口，两个入口分别打开对应原文

#### Scenario: 只有疑似冲突或缺口
- **WHEN** 调查摘要提到 conflict 但最终 answer 没有双边可引用 Evidence
- **THEN** 页面将其显示为待核验线索或缺口，不包装成已证实冲突卡

### Requirement: 降级、取消与网络错误有稳定恢复
原生 App MUST 在 fallback_summary 表示降级时给出用户可理解的受影响阶段和结果边界，MUST NOT 默认暴露 provider、model、堆栈或原始错误；cancelled、请求错误和服务端失败 MUST 使用彼此不同的持久状态与恢复动作。

#### Scenario: auto 路由降级到 quick
- **WHEN** Run 实际模式为 quick 且 fallback 表示回答模式路由不可用
- **THEN** 页面说明已改用快速回答并保留回答，不伪装成按计划完成深度查找

#### Scenario: 工具部分失败
- **WHEN** fallback_summary 显示部分检索或证据步骤失败但仍有有效回答
- **THEN** 页面标记部分结果并保留有效引用，提供重试但不隐藏失败范围

#### Scenario: 用户取消
- **WHEN** Run 终态为 cancelled
- **THEN** 页面显示已取消、无正常助手回答和可重新提问操作

#### Scenario: 网络不可用
- **WHEN** 仅移动网络请求失败且服务端 Run 状态未知
- **THEN** 页面显示连接问题和刷新动作，不把 Run 改成本地 failed/cancelled

#### Scenario: partial 或可恢复降级
- **WHEN** answer.status 为 partial，或 fallback_summary 指示已有有效结果但可通过新 Run 补查
- **THEN** 页面提供重新提问或适配的恢复入口，不自行把 insufficient 改写为 partial

#### Scenario: partial 或 fallback 重新提问
- **WHEN** 用户从 partial 或带可恢复 fallback 的回答选择重新提问
- **THEN** 客户端以原问题创建新的 Run，并保留旧回答和旧引用快照

### Requirement: 长内容 Sheet 可滚动且恢复对话
原生 App MUST 让 History、Scope、Mode 与 Citation Bottom Sheet 的长内容在 Sheet 内独立滚动，并在关闭后恢复原对话阅读状态；Sheet 不得因长项目名、引用原文、错误或选项列表遮挡关闭操作或 Composer。

#### Scenario: 长引用原文
- **WHEN** Citation quote 或 Source 标题超过一屏
- **THEN** 用户可在 Citation Sheet 内滚动到全部内容并始终可关闭 Sheet

#### Scenario: 长历史或选项
- **WHEN** History、Scope 或 Mode 列表超过可用高度
- **THEN** 对应 Sheet 内可滚动，关闭后对话仍保留原消息位置和输入状态

### Requirement: 回答后续动作使用结构化协议
原生回答展示 MUST 根据服务端回答状态、最终 citations、source Run 与可用目标项目构造「整理成知识」结构化动作；MUST NOT 通过解析回答正文、固定字符串或模型自报 save_recommended 决定可写状态。动作必须保留来源回答与生成时范围。

#### Scenario: completed 回答提供结构化动作
- **WHEN** 服务端返回 completed 回答、source Run 和有效 citations
- **THEN** 客户端以 source_run_id 发起 draft_candidate，不从正文反推引用或项目

#### Scenario: partial 回答提供受限动作
- **WHEN** 服务端返回 partial 回答且仍有有效 citations
- **THEN** 动作说明只整理有依据部分，未解决 gaps 不进入 Candidate 草稿事实

#### Scenario: 历史回答恢复动作
- **WHEN** 用户重新打开包含可用历史回答的 Conversation
- **THEN** 动作仍锚定该历史 source Run 的范围快照；服务端判定 Evidence 失效时显示可恢复错误而非改用当前回答

### Requirement: 回答、草稿与 Candidate 回执语义分离
原生 App MUST 分别使用「基于正式知识的即时回答」「AI 草稿 · 未创建候选」「已创建待确认知识 · 尚未写入正式知识」表达三类对象；任何 Badge、标题、按钮或 Toast MUST NOT 把 Draft/Candidate 显示为正式 Entry。

#### Scenario: 草稿生成完成
- **WHEN** operation Run 返回 draft 状态
- **THEN** 草稿卡使用 AI 建议语义并提供编辑/确认动作，不使用 confirmed 语义

#### Scenario: Candidate 创建完成
- **WHEN** Draft 确认并关联 pending Candidate
- **THEN** 回执显示待确认状态、来源与目标项目，不显示“正式知识已保存”

### Requirement: 回答正文的要点卡渲染
原生 App MUST 在 `answer.points` 非空时把回答正文渲染为要点卡：分组标题、全回答连续编号与要点正文；MUST 在 `points` 缺失或为空时回退为现有纯文本正文 + 底部来源条，历史回答不得出现回归或伪富文本。

#### Scenario: 新回答带结构化要点
- **WHEN** 回答包含 `points` 且至少一条有效要点
- **THEN** 页面按分组标题、连续编号展示每条要点正文，不在要点内展示来源入口

#### Scenario: 历史回答无要点
- **WHEN** 回答不包含 `points`（历史数据或旧模型输出）
- **THEN** 页面保留现有纯文本正文与底部来源条，不显示空要点区

#### Scenario: 分组标题与编号可读
- **WHEN** 要点存在 `section` 分组
- **THEN** 分组标题以更醒目的样式展示，连续编号读屏可朗读

### Requirement: 底部来源条可核验可访问
原生 App MUST 在回答卡底部展示全部引用来源横条（有 `points` 与无 `points` 一致），每条来源为可点击 chip（最小触控高度 44），点击后展示对应 Source 原文与 Entry 摘要；MUST NOT 把 AI 即时回答、草稿或 Candidate 标为正式知识。

#### Scenario: 点击底部来源 chip
- **WHEN** 用户点击回答卡底部的某个来源 chip
- **THEN** 打开证据原文 Sheet，展示该引用的 Entry 与 Source 原文，来源关系由应用层校验

#### Scenario: 触控与读屏
- **WHEN** 用户使用读屏或小尺寸触控
- **THEN** 来源 chip 提供 `查看引用：{Entry 标题}` 语义且最小触控高度为 44

#### Scenario: 语义不混淆
- **WHEN** 回答、草稿与待确认 Candidate 同屏出现
- **THEN** 要点卡保持「基于正式知识」的即时回答语义，不出现「已归档」或「正式知识」文案

### Requirement: 回答引用详情提供 Entry 定向后续操作
原生回答的 citation 详情 MUST 在当前 Entry 可用于写入时提供结构化“修订这条知识”动作，并把 target_entry_id 与 source_run_id 绑定到服务端已返回对象；客户端 MUST NOT 允许用户或模型自由填写对象 ID。该动作不改变 citation 的阅读与原文核验主用途。

#### Scenario: 当前有效引用显示修订动作
- **WHEN** completed/partial 回答的 citation 对应当前可写 Entry
- **THEN** 引用详情在 Entry/Source 原文之后提供目标明确的修订入口

#### Scenario: 只查看来源原文
- **WHEN** 用户打开 citation 但不发起修订
- **THEN** 页面只展示 Entry 与 Source Evidence，不创建 Draft、Run 或任何写对象

### Requirement: 回答、Candidate Draft 与 Entry Revision 语义不混淆
原生 App MUST 将“整理成知识”表达为创建待确认 Candidate，将“修订这条知识”表达为对既有正式 Entry 的候选修改；两种动作、草稿、确认后果与回执 MUST 使用不同标题和文案，MUST NOT 把任一 AI 草稿显示为已执行。

#### Scenario: 同一回答提供两类后续动作
- **WHEN** 回答既可整理为 Candidate 且某条 citation 可修订
- **THEN** 页面分别说明“创建待确认知识”和“修改现有正式知识”，用户能看懂目标及确认后果

#### Scenario: Entry Revision 尚未确认
- **WHEN** 修订草稿已生成但未应用
- **THEN** 回答与 Entry 仍保持正式原内容，草稿标识为 AI 建议且不显示已更新

