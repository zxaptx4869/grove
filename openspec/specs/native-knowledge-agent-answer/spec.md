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

