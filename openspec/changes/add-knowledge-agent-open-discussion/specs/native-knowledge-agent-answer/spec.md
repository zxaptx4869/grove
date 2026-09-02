## ADDED Requirements

### Requirement: 回答下展示服务端确认的紧凑依据概览
原生 App MUST 根据服务端结构化 `answer_basis` 在整条回答下展示紧凑、可展开的依据概览，区分“你的知识”“你提供的信息”“AI 通用知识”和外部材料边界；MUST NOT 解析回答正文、工具过程或模型自报文本推断依据，也 MUST NOT 用“可靠来源”“已验证事实”等文案替用户判断内容真伪。

#### Scenario: 模型优先回答依据
- **WHEN** completed 回答没有 Citation 且 basis 标记使用模型通用知识
- **THEN** 回答下显示“AI 通用知识 · 未使用你的知识库 · 未检索实时外部资料”，不显示伪来源入口

#### Scenario: 混合回答依据
- **WHEN** basis 包含两个 Grove Citation、两条用户陈述和模型通用知识
- **THEN** 紧凑概览分别显示三类实际依据，Grove 项仍可打开 Citation 原文，用户陈述项可查看对应消息摘要

#### Scenario: 需要外部材料
- **WHEN** basis 的 external material 状态为 required_unavailable
- **THEN** 回答附近明确显示当前未检索实时外部材料和因此未覆盖的边界，不暗示已经联网

#### Scenario: 历史回答没有 basis
- **WHEN** 旧 Run 不包含 `answer_basis`
- **THEN** 页面保持旧回答正文、状态、来源条与 Citation Sheet，不猜测或补造 AI 通用知识、用户陈述或外部材料标签

#### Scenario: 依据详情长内容
- **WHEN** 用户陈述摘要、Citation 或外部边界超过可用高度
- **THEN** 依据详情在 Sheet 内独立滚动、始终可关闭，并在关闭后恢复对话阅读位置

## MODIFIED Requirements

### Requirement: 结构化回答状态清晰区分
原生 App MUST 依据结构化 `answer.status` 展示 completed、partial、insufficient、failed、clarification，并结合而非仅依赖 Run 状态；AI 即时回答 MUST 标识为“AI 即时回答”及其实际依据，不得一律标为“基于正式知识”，也不得显示为 Candidate 或正式 Entry。

#### Scenario: 正常带引用回答
- **WHEN** answer 为 completed 且有有效 citations，basis 只包含 Grove
- **THEN** 页面展示回答正文、生成时范围、来源条与“基于你的知识”依据语义

#### Scenario: 正常无引用回答
- **WHEN** answer 为 completed、citations 为空且 basis 合法标记模型通用知识或用户陈述
- **THEN** 页面展示正常即时回答和实际依据，不因为没有 Citation 显示知识不足或“基于正式知识”

#### Scenario: 部分回答
- **WHEN** answer 为 partial 且仍有有效内容
- **THEN** 页面保留有效回答、实际依据和可用引用，并在内容附近说明哪些部分降级、失效或未覆盖

#### Scenario: 知识不足
- **WHEN** answer.status 为 insufficient，无论 quick Run 是 completed 还是调查 Run 是 partial
- **THEN** 页面统一显示依据不足语义、`insufficient_note` 和可用 gaps，不使用成功完成文案掩盖不足

#### Scenario: 澄清回答
- **WHEN** answer.status 为 clarification
- **THEN** 页面显示需要用户补充的信息并允许在同一 Conversation 继续回复，不把它当失败或事实答案

#### Scenario: 回答失败
- **WHEN** answer.status 为 failed 或 Run 为 failed
- **THEN** 页面显示持久错误、已知原因和重新提问操作，不用 toast 代替可恢复状态

### Requirement: 回答后续动作使用结构化协议
原生回答展示 MUST 根据服务端返回的旧 Candidate Draft 资格、回答状态、最终 citations、answer basis、source Run 与可用目标项目构造固定“整理成知识”结构化动作；MUST NOT 通过解析回答正文、仅判断 Citation 非空、固定字符串或模型自报 save_recommended 决定可写状态。动作必须保留来源回答与生成时范围，且本 change 不为开放或混合回答创建新的沉淀入口。

#### Scenario: 纯 Grove completed 回答提供结构化动作
- **WHEN** 服务端返回 completed 回答、source Run、有效 citations，并明确该 Run 未采用用户陈述、模型通用知识或外部材料
- **THEN** 客户端可以 source_run_id 发起旧 `draft_candidate`，不从正文反推引用、basis 或项目

#### Scenario: 纯 Grove partial 回答提供受限动作
- **WHEN** 服务端判定 partial 回答仍有完全由有效 Grove Evidence 支撑的可整理部分
- **THEN** 动作说明只整理有依据部分，未解决 gaps 不进入 Candidate 草稿事实

#### Scenario: 模型优先或混合回答不显示旧入口
- **WHEN** answer basis 包含用户陈述、模型通用知识或当前不可用外部材料
- **THEN** 页面不显示固定“整理成知识”，即使回答同时包含一个或多个 Grove Citation

#### Scenario: 历史回答恢复动作
- **WHEN** 用户重新打开本 change 上线前生成且按旧规则可用的历史回答
- **THEN** 动作仍锚定该历史 source Run 的范围快照；服务端按旧 Evidence 规则判断资格，Evidence 失效时显示可恢复错误而非改用当前回答
