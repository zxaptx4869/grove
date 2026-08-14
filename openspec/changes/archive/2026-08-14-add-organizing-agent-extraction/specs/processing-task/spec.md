## MODIFIED Requirements

### Requirement: Provider 边界
系统 MUST 通过 `ProcessingProvider` 抽象执行处理；默认使用 Organizing 处理 Provider，离线模式确定性；真实 Provider 通过 Organizing Agent 执行并产出版本化 Extraction 与 Candidate；未接入的真实 Provider MUST 明确报错。

#### Scenario: Demo 处理
- **WHEN** 当前 Workspace 未配置真实模型密钥
- **THEN** Organizing 处理 Provider 使用离线确定性模型完成处理，不依赖外部服务

#### Scenario: 真实 Provider 处理
- **WHEN** 当前 Workspace 配置了真实模型密钥
- **THEN** Organizing 处理 Provider 调用 Organizing Agent，并产出版本化 Extraction 与 Candidate

#### Scenario: 未接入 Provider 报错
- **WHEN** 使用未接入的真实 Provider
- **THEN** 处理明确报「未接入」，而不是静默成功
