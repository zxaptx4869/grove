## MODIFIED Requirements

### Requirement: 应用 AI 修订建议

系统 MUST 支持用户在确认后应用 AI 修订草稿：应用 MUST 按用户确认后的字段更新 Entry、追加一条 `ai_revision` 类型版本并记录变更说明；仅当草稿标记 `external_supplemented=true` 时，应用 MUST 创建「AI 修订建议」虚拟 Source（记录用户指令、AI 输出与 provider/model）并加入 Entry 来源证据；`external_supplemented=false` 的纯格式/表述调整 MUST 只追加版本、不新增来源证据；原有来源证据 MUST 保持不变；未应用时 Entry MUST 保持不变；越权 Entry MUST 请求失败（404）。

#### Scenario: 外部补充应用时沉淀虚拟来源
- **WHEN** 用户确认并应用标记了 `external_supplemented=true` 的 AI 修订草稿
- **THEN** Entry 按确认后的字段更新，来源证据新增「AI 修订建议」虚拟 Source（可打开查看指令与 AI 输出），并追加 `ai_revision` 版本带变更说明，原有来源证据不变

#### Scenario: 纯格式调整不新增来源
- **WHEN** 用户确认并应用标记了 `external_supplemented=false` 的 AI 修订草稿（仅调整格式/表述）
- **THEN** Entry 更新并追加 `ai_revision` 版本与变更说明，但不创建虚拟 Source、不新增来源证据

#### Scenario: 未应用保持不变
- **WHEN** 用户放弃或关闭修订建议面板
- **THEN** Entry 内容、来源与版本均不发生变化

#### Scenario: 越权 Entry 不可应用
- **WHEN** 应用请求的 Entry 不属于当前 Workspace
- **THEN** 请求失败（404），不修改任何数据
