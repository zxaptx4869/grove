## RENAMED Requirements

- FROM: `### Requirement: 相似推荐采用确定性召回与语义重排`
- TO: `### Requirement: 相似推荐采用混合召回与语义重排`

## MODIFIED Requirements

### Requirement: 相似推荐采用混合召回与语义重排
系统 MUST 复用与语义搜索相同的混合召回与文本模型语义重排流程生成相似推荐；embedding 未配置或失败时 MUST 降级为确定性召回；返回结果 MUST 带相关理由；未配置文本模型密钥时 MUST 明确降级。

#### Scenario: 复用混合召回与重排
- **WHEN** 系统生成相似推荐且 embedding 可用
- **THEN** 使用确定性召回与 embedding 召回合并缩小候选集，再由文本模型语义重排并返回相关理由

#### Scenario: embedding 降级
- **WHEN** 当前 Workspace 未配置 embedding 或编码失败
- **THEN** 使用确定性召回生成候选集并明确标记降级

#### Scenario: 未配置密钥降级
- **WHEN** 当前 Workspace 未配置文本模型密钥
- **THEN** 按召回分数降序返回确定性召回结果并标记为降级，不调用外部服务
