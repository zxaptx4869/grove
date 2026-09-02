# knowledge-agent-answer-basis Specification

## Purpose
TBD - created by archiving change add-knowledge-agent-open-discussion. Update Purpose after archive.
## Requirements
### Requirement: 普通回答按用户约束选择形成依据
系统 MUST 在 `actual_result_mode=answer` 时为普通问题选择受限的内部依据策略 `knowledge_only`、`knowledge_first`、`model_first`、`hybrid` 或 `external_needed`；策略 MUST 尊重用户显式依据覆盖和当前消息中的明确限制，模型 MUST NOT 自行放宽限制、指定 Workspace/项目或获得写权限。结构化 Entry 结果 MUST NOT 执行回答依据规划。

#### Scenario: 通用解释使用模型优先
- **WHEN** 用户以自动依据模式询问无需个人知识或实时材料的通用概念
- **THEN** 系统可以选择 `model_first`、不调用 Grove 工具并使用模型通用能力回答

#### Scenario: 个性化问题读取 Grove
- **WHEN** 用户询问自己的项目记录、历史决定或已有经验
- **THEN** 系统选择需要 Grove 的策略，并只在 Run 固化的 Workspace/项目范围内读取正式知识

#### Scenario: 显式仅使用个人知识库
- **WHEN** 用户通过结构化覆盖选择“仅使用我的知识库”
- **THEN** 系统固定 `knowledge_only`，不得允许规划器或回答器引入模型通用知识或外部材料

#### Scenario: 自然语言限制收紧策略
- **WHEN** 自动依据请求中明确写出“只根据我的知识库回答”或等价限制
- **THEN** 规划结果必须收紧为 `knowledge_only`，即使模型认为通用知识有帮助也不得放宽

#### Scenario: 依据规划失败
- **WHEN** 依据规划模型未配置、超时、调用失败或返回非法结构
- **THEN** 系统显式记录 fallback 并安全回退 `knowledge_only`，不得静默改用模型通用知识

### Requirement: 实际回答依据由服务端持久化和派生
系统 MUST 为每个终态回答保存版本化实际依据，至少包括最终有效 Grove Citation 数与 Entry 数、采用的当前话题用户消息 ID、是否允许并使用模型通用知识、外部材料状态；Grove 数量 MUST 从最终通过校验的当前 Run Evidence 派生，用户消息 ID MUST 来自服务端允许集合，模型 MUST NOT 自由声明或伪造实际依据。

#### Scenario: 模型优先回答没有伪来源
- **WHEN** `model_first` 回答未调用 Grove 工具且正常完成
- **THEN** 实际依据记录标记模型通用知识、Grove Citation 数为零，且不创建 Citation、Source 或 Evidence

#### Scenario: 混合回答保存多类依据
- **WHEN** 回答采用当前话题用户陈述、模型通用知识和两个最终有效 Grove Citation
- **THEN** 系统保存经校验的用户消息 ID、模型知识标记、两个 Citation 及其 Entry 计数，历史恢复返回同一依据快照

#### Scenario: 模型返回未知用户消息
- **WHEN** 依据规划输出不在服务端允许集合内的消息 ID
- **THEN** 系统丢弃该 ID、记录异常且不得读取或展示对应消息内容

#### Scenario: Citation 在最终校验中失效
- **WHEN** 规划阶段读取了 Grove，但最终所有 Evidence 句柄都无效
- **THEN** 实际依据中的 Grove 使用量为零，界面不得仅凭工具调用宣称回答使用了“你的知识”

### Requirement: 当前话题用户陈述可以作为非正式前提
系统 MUST 只允许当前用户消息和同一 Conversation、同一范围快照、当前上下文链内的有界近期用户消息作为“用户提供的信息”；`new_topic`、范围切换和未完成澄清 MUST 切断旧话题陈述。用户陈述 MUST NOT 被包装成 Grove Citation、Source、Entry 或工作集 Entry。

#### Scenario: 继续话题采用用户前提
- **WHEN** 用户先说明“预算上限是 30 万”，随后在同一话题追问如何分配
- **THEN** 系统可以采用前一条用户消息作为个人前提，并在实际依据中保存该消息 ID

#### Scenario: 新话题不继承旧陈述
- **WHEN** 用户显式开始新话题后提出一个省略了关键条件的问题
- **THEN** 系统不得把旧话题中的预算陈述作为本轮依据，应独立回答或请求澄清

#### Scenario: 范围切换切断陈述
- **WHEN** Conversation 从一个项目切换到 Workspace 或另一项目
- **THEN** 新范围回答不得自动采用切换前范围中的用户陈述

#### Scenario: 助手历史不是用户陈述
- **WHEN** 近期助手回答包含未由当前 Run 重新支持的说法
- **THEN** 系统不得把该说法作为用户陈述、Grove Evidence 或模型外的事实依据

### Requirement: 回答状态与 Citation 是否存在解耦
系统 MUST 根据核心请求是否完成、是否仍有缺口和执行是否失败确定 `completed`、`partial`、`insufficient` 或 `failed`；没有 Grove Citation 本身 MUST NOT 导致知识不足，存在零散 Citation 本身也 MUST NOT 把未回答的核心问题标记为完成。

#### Scenario: 无 Citation 的正常开放回答
- **WHEN** 模型通用能力在允许范围内完整回答通用问题且未调用 Grove
- **THEN** answer.status 为 `completed`，citations 为空，实际依据明确为 AI 通用知识

#### Scenario: knowledge_only 没有证据
- **WHEN** `knowledge_only` Run 未找到能够直接回答核心问题的有效 Evidence
- **THEN** answer.status 为 `insufficient`，不得使用模型通用知识补齐

#### Scenario: 混合请求仅完成一部分
- **WHEN** 回答提供了可用的一般分析，但用户要求的个人知识部分没有找到或工具部分失败
- **THEN** answer.status 为 `partial`，保留有效内容并明确缺少的 Grove 部分或失败边界

#### Scenario: 回答模型不可用
- **WHEN** 没有可提交的合法回答且回答模型未配置或调用失败
- **THEN** answer.status 或 Run 终态为 `failed`，不得用静态模板伪装成正常 AI 回答

### Requirement: Grove Citation 与模型知识保持不同证明边界
系统 MUST 继续只允许最终 Grove Citation 指向当前 Run 实际读取并完成对象、权限、版本和 quote 对应校验的 Evidence；模型通用知识与用户陈述可以进入允许的回答正文，但 MUST NOT 生成伪 Citation、伪 Source 原文或“已验证事实”语义。

#### Scenario: 开放要点没有 Grove 依据
- **WHEN** 允许模型通用知识的回答包含没有 Evidence 支撑的解释性要点
- **THEN** 系统可以保留该要点，但只在整条回答依据中标记 AI 通用知识，不为该要点生成 Citation

#### Scenario: 开放回答包含未知 Evidence 句柄
- **WHEN** 回答模型输出未知、越权或不属于当前 Run 的 Evidence 句柄
- **THEN** 系统丢弃对应 Grove 引用并按剩余合法内容重新计算状态与实际依据

#### Scenario: 用户陈述与 Grove 知识不一致
- **WHEN** 当前用户陈述与有效 Grove Entry 内容不一致
- **THEN** 回答并列说明两者及形成依据，不静默覆盖 Entry，也不替用户裁决哪一方客观正确

### Requirement: 外部材料边界必须诚实可见
系统 MUST 在问题依赖当前时效、专业规则或其他实时外部材料而本阶段未接入外部工具时使用 `external_needed` 或等价的服务端边界；系统可以提供一般框架，但 MUST NOT 声称已经联网、已经核验当前材料或把模型训练知识描述为实时结果。

#### Scenario: 当前规则问题需要外部材料
- **WHEN** 用户询问当前生效的政策、价格或规则且没有真实外部工具结果
- **THEN** 回答明确未检索实时外部资料，并根据核心问题实际完成程度返回 `partial` 或 `insufficient`

#### Scenario: 高风险问题提供一般框架
- **WHEN** 用户询问依赖当前专业材料的医疗、法律或金融决定
- **THEN** 系统可以说明一般概念和待核对事项，但必须显示外部材料缺口且不伪造专业结论来源

### Requirement: 开放回答不产生知识写入副作用
即时回答、依据规划与依据概览 MUST NOT 创建 Source、Candidate、Entry 或 Directory 操作，也 MUST NOT 修改正式对象；回答仍是 AI 即时输出而不是正式知识，后续写入必须由独立的用户发起、审阅和确认协议完成。

#### Scenario: 模型优先讨论正常完成
- **WHEN** 开放讨论形成一段模型通用建议且用户未发起结构化写知识操作
- **THEN** 系统只持久化 Conversation、Message、Run 与回答依据，不创建任何知识对象

#### Scenario: 混合回答正常完成
- **WHEN** 混合回答引用了正式 Entry 并结合用户陈述
- **THEN** 引用只用于回答可追溯性，不自动补充、修订或新建任何 Entry

