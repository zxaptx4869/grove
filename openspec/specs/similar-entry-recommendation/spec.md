# similar-entry-recommendation Specification

## Purpose
推荐同一项目内语义相关的其他正式 Entry 并排除自身，未配置密钥时降级返回确定性召回结果并附理由。
## Requirements
### Requirement: 同一项目内相似 Entry 推荐
系统 MUST 为指定 Entry 推荐其所属项目内语义相关的其他正式 Entry；推荐结果 MUST 排除该 Entry 自身；范围 MUST 限定该 Entry 所属项目与当前 Workspace。

#### Scenario: 推荐同一项目相似 Entry
- **WHEN** 用户打开某 Entry 的详情
- **THEN** 返回该 Entry 所属项目内语义相关的其他正式 Entry

#### Scenario: 排除自身
- **WHEN** 系统为 Entry 生成相似推荐
- **THEN** 推荐结果不包含该 Entry 自身

#### Scenario: 无相似 Entry
- **WHEN** 项目内没有其他语义相关的正式 Entry
- **THEN** 返回空结果

### Requirement: 相似推荐采用确定性召回与语义重排
系统 MUST 复用与语义搜索相同的确定性召回与文本模型语义重排流程生成相似推荐；返回结果 MUST 带相关理由；未配置文本模型密钥时 MUST 明确降级。

#### Scenario: 复用召回与重排
- **WHEN** 系统生成相似推荐
- **THEN** 使用确定性召回缩小候选集，再由文本模型语义重排并返回相关理由

#### Scenario: 未配置密钥降级
- **WHEN** 当前 Workspace 未配置文本模型密钥
- **THEN** 按召回分数降序返回确定性召回结果并标记为降级，不调用外部服务

### Requirement: 越权项目不可见
用户请求相似推荐的 Entry 不属于当前 Workspace 时 MUST 失败（404），不暴露其他 Workspace 数据。

#### Scenario: 越权 Entry 404
- **WHEN** 用户请求的 Entry 不属于当前 Workspace
- **THEN** 请求失败（404），不返回任何数据
