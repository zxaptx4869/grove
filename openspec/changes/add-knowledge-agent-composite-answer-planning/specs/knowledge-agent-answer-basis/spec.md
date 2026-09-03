## MODIFIED Requirements

### Requirement: 普通回答按用户约束选择形成依据
系统 MUST 在 `actual_result_mode=answer` 时尊重用户显式依据覆盖和当前消息中的明确限制。启用复合回答的 quick Run MUST 为每项回答义务分别选择 `grove_only`、`grove_required`、`model_allowed` 或 `external_required`，而不是要求整条消息只有一个内部依据策略；未启用复合回答或 investigate Run 可以继续使用兼容策略 `knowledge_only`、`knowledge_first`、`model_first`、`hybrid` 或 `external_needed`。任何策略 MUST NOT 自行放宽限制、指定 Workspace/项目或获得写权限，结构化 Entry 结果 MUST NOT 执行回答依据规划。

#### Scenario: 通用解释使用模型知识
- **WHEN** 用户以自动依据模式询问无需个人知识或实时材料的通用概念
- **THEN** quick 复合计划可以生成单个 `model_allowed` 义务、不调用 Grove 工具并使用模型通用能力回答；兼容路径可以选择 `model_first`

#### Scenario: 个性化问题读取 Grove
- **WHEN** 用户询问自己的项目记录、历史决定或已有经验
- **THEN** 对应回答义务要求 Grove，并只在 Run 固化的 Workspace/项目范围内读取正式知识

#### Scenario: 一条消息使用多种依据
- **WHEN** 用户要求先解释一般概念，再结合个人知识分析来源和等级
- **THEN** 系统允许概念义务使用模型知识、个人部分要求 Grove，并在同一回答中分别保存实际依据和覆盖结果

#### Scenario: 显式仅使用个人知识库
- **WHEN** 用户通过结构化覆盖选择“仅使用我的知识库”
- **THEN** 系统把全部回答义务固定为 `grove_only`，兼容路径固定 `knowledge_only`，不得允许规划器或回答器引入模型通用知识或外部材料

#### Scenario: 自然语言限制收紧策略
- **WHEN** 自动依据请求中明确写出“只根据我的知识库回答”或等价限制
- **THEN** 服务端将全部逐项策略收紧为 `grove_only`，兼容规划结果收紧为 `knowledge_only`，即使模型认为通用知识有帮助也不得放宽

#### Scenario: 依据规划失败
- **WHEN** 复合或兼容依据规划模型未配置、超时、调用失败或返回非法结构
- **THEN** 系统显式记录对应 fallback 并安全进入既有 `knowledge_only` 兼容路径，不得静默改用模型通用知识

### Requirement: 实际回答依据由服务端持久化和派生
系统 MUST 为每个终态回答保存版本化实际依据，至少包括最终有效 Grove Citation 数与 Entry 数、采用的当前话题用户消息 ID、是否允许并使用模型通用知识、外部材料状态；复合回答还 MUST 按回答义务保存合法 Evidence、结构化 result handle、用户消息与模型知识的实际使用。Grove 数量 MUST 从最终通过校验的当前 Run Evidence 派生，结构化事实 MUST 从实际工具结果派生，用户消息 ID MUST 来自服务端允许集合，模型 MUST NOT 自由声明或伪造实际依据。

#### Scenario: 模型优先回答没有伪来源
- **WHEN** 单一 `model_allowed` 或兼容 `model_first` 回答未调用 Grove 工具且正常完成
- **THEN** 实际依据记录标记模型通用知识、Grove Citation 数为零，且不创建 Citation、Source 或 Evidence

#### Scenario: 混合回答保存多类依据
- **WHEN** 回答采用当前话题用户陈述、模型通用知识和两个最终有效 Grove Citation
- **THEN** 系统保存经校验的用户消息 ID、模型知识标记、两个 Citation 及其 Entry 计数，复合回答同时保存各自关联义务，历史恢复返回同一依据快照

#### Scenario: 结构化事实保存真实工具依据
- **WHEN** 某回答义务使用完整执行的 count 工具事实
- **THEN** 系统在逐项覆盖中保存对应 result handle、完整性与实际数值来源，不把它计为 Citation 或模型知识

#### Scenario: 模型返回未知用户消息
- **WHEN** 依据规划输出不在服务端允许集合内的消息 ID
- **THEN** 系统丢弃该 ID、记录异常且不得读取或展示对应消息内容

#### Scenario: Citation 在最终校验中失效
- **WHEN** 规划阶段读取了 Grove，但最终所有 Evidence 句柄都无效
- **THEN** 实际依据中的 Grove 使用量为零，相关回答义务不得标记为 Grove 已覆盖，界面不得仅凭工具调用宣称回答使用了“你的知识”

### Requirement: 回答状态与 Citation 是否存在解耦
系统 MUST 根据每项核心回答义务是否完成、是否仍有缺口和执行是否失败确定 `completed`、`partial`、`insufficient` 或 `failed`；没有 Grove Citation 本身 MUST NOT 导致知识不足，存在零散 Citation 或工具事实本身也 MUST NOT 把未回答的核心义务标记为完成。

#### Scenario: 无 Citation 的正常开放回答
- **WHEN** 模型通用能力在允许范围内完整回答全部通用义务且未调用 Grove
- **THEN** answer.status 为 `completed`，citations 为空，实际依据明确为 AI 通用知识

#### Scenario: knowledge_only 没有证据
- **WHEN** `knowledge_only` 或 `grove_only` Run 未找到能够直接回答核心义务的有效 Evidence 或工具事实
- **THEN** answer.status 为 `insufficient`，不得使用模型通用知识补齐

#### Scenario: 混合请求仅完成一部分
- **WHEN** 回答提供了可用的一般分析，但用户要求的个人知识、统计或其他核心义务没有找到或工具部分失败
- **THEN** answer.status 为 `partial`，保留有效内容并明确缺少的义务、Grove 部分或失败边界

#### Scenario: 零散 Citation 没有覆盖首个问题
- **WHEN** 模型回答了两个有 Grove Evidence 的义务但遗漏一个允许通用知识的概念义务
- **THEN** 系统把遗漏项列入 gaps 并将整体状态标为 partial，不因存在 Citation 而标记 completed

#### Scenario: 回答模型不可用
- **WHEN** 没有可提交的合法回答或确定性工具事实且回答模型未配置或调用失败
- **THEN** answer.status 或 Run 终态为 `failed`，不得用静态模板伪装成正常 AI 回答
