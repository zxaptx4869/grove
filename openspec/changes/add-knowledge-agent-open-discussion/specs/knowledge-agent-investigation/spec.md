## ADDED Requirements

### Requirement: 深度查找必须执行真实 Grove 调查并遵守依据限制
`investigate` MUST 继续表示在 Run 固化范围内执行现有有界 Grove 只读调查，而不是仅让模型生成更长回答；显式 investigate 请求 MUST 创建 Investigation 并实际经过受控查询边界。依据策略可以决定调查后是否允许加入用户陈述或模型通用知识，但 MUST NOT 放宽轮次、查询、Entry、Evidence、取消、恢复与 Workspace/项目限制。

#### Scenario: 显式 investigate 强制 Grove 调查
- **WHEN** 用户显式选择深度查找并以自动依据模式提交问题
- **THEN** 系统创建有界 Investigation、执行至少一次合法 Grove 查询或确定性停止，并返回真实轮次与停止原因

#### Scenario: 自动 model_first 不伪装调查
- **WHEN** 自动依据选择 `model_first` 且用户没有显式要求 investigate
- **THEN** 系统确定性使用 quick 开放回答，不创建 Investigation 或伪造调查模型调用

#### Scenario: investigate 与 knowledge_only 无证据
- **WHEN** 用户同时选择 investigate 与 `knowledge_only`，调查在预算内没有找到可回答核心问题的 Evidence
- **THEN** 调查以真实停止原因结束且回答为 `insufficient`，不得使用模型通用知识补齐

#### Scenario: investigate 后提供一般回答
- **WHEN** 用户允许模型通用知识，调查没有找到相关 Grove Evidence，但一般分析仍能回答核心问题的一部分或全部
- **THEN** 系统保留真实调查摘要，明确 Grove 未命中，并按核心问题完成程度返回 `partial` 或 `completed` 的一般回答

#### Scenario: 调查工具失败后降级
- **WHEN** Investigation 的查询或 Evidence 工具不可用，但回答模型仍能提供允许范围内的一般内容
- **THEN** Run 显示受影响工具与 fallback，回答最多按合法内容返回 `partial`，不得伪装成正常完成的 Grove 调查
