## ADDED Requirements

### Requirement: AI Provider 抽象接口
后端 MUST 定义 `AIProvider` 抽象接口，包含异步补全方法与结构化的输入输出类型（Pydantic 模型）；输入 SHALL 包含系统提示与用户消息，输出 SHALL 为带 `is_candidate` 标记的候选结果。

#### Scenario: 接口可被实现与调用
- **WHEN** 实现类实例化并调用补全方法
- **THEN** 返回结构化候选结果，`is_candidate` 为 `true`

### Requirement: Demo Provider 确定性实现
后端 MUST 提供 `DemoProvider`，其输出 MUST 是确定性的（相同输入产生相同输出），不依赖任何外部 API 或网络。

#### Scenario: 相同输入产生相同输出
- **WHEN** 以相同输入连续两次调用 `DemoProvider`
- **THEN** 两次返回的候选内容完全一致

### Requirement: Provider 工厂可切换
后端 MUST 提供 `get_ai_provider` 工厂，根据配置值选择 provider：`demo` 返回 `DemoProvider`，`deepseek` 与 `doubao` SHALL 有对应定义但未接入真实 API（调用时明确报错或返回未实现说明）。

#### Scenario: 默认使用 Demo Provider
- **WHEN** 未配置 AI 供应商时调用 `get_ai_provider`
- **THEN** 返回 `DemoProvider` 实例

#### Scenario: 未接入供应商明确提示
- **WHEN** 配置为 `deepseek` 或 `doubao` 时调用 provider
- **THEN** 行为明确标记为未接入，不得静默调用外部服务

### Requirement: AI 输出候选铁律
AI Provider 的输出 SHALL 始终标记为候选结果，且仓库守则 MUST 声明 AI 输出不得直接写入或覆盖正式记录。

#### Scenario: 候选标记可被消费方识别
- **WHEN** 消费方读取 provider 返回结果
- **THEN** 能通过 `is_candidate` 字段判断该结果为候选，且守则文档禁止其直接成为正式记录
