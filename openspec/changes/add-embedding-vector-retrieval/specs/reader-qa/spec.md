## MODIFIED Requirements

### Requirement: 证据召回复用语义检索
系统 MUST 复用语义检索的混合召回与文本模型语义重排，按用户问题召回最多 15 条已确认 Entry 作为问答上下文；embedding 未配置或失败时 MUST 降级为确定性召回；未配置文本模型密钥或模型调用失败时 MUST 降级为确定性召回结果并标记，不得静默调用外部服务。

#### Scenario: 按问题召回上下文
- **WHEN** 用户输入问题并发起问答且 embedding 可用
- **THEN** 系统返回确定性召回与 embedding 召回合并后的语义相关已确认 Entry 作为回答上下文

#### Scenario: embedding 降级
- **WHEN** 当前 Workspace 未配置 embedding 或编码失败
- **THEN** 系统使用确定性召回结果作为上下文并标记降级，不中断问答

#### Scenario: 模型失败降级
- **WHEN** 文本模型不可用（未配置密钥或调用失败）
- **THEN** 使用确定性召回结果作为上下文并标记降级，不中断问答
