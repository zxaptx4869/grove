## MODIFIED Requirements

### Requirement: 项目内相似 Entry 检索

系统 MUST 在候选进入确认台前，于候选所属项目内检索相似正式 Entry；检索范围 MUST 限定当前 Workspace 的同一项目；检索 MUST 使用关键词与字符重叠的确定性召回与 embedding 向量召回合并检索，embedding 未配置或失败时 MUST 降级为仅确定性召回；不得跨项目或跨 Workspace 检索。

#### Scenario: 项目内有相似 Entry
- **WHEN** 候选所属项目内存在标题或内容相近的正式 Entry 且 embedding 可用
- **THEN** 系统返回确定性召回与 embedding 召回去重合并后的 Entry 供关系判断使用

#### Scenario: embedding 降级
- **WHEN** 当前 Workspace 未配置 embedding 或编码失败
- **THEN** 系统使用确定性召回检索相似 Entry 并明确标记降级

#### Scenario: 项目内没有 Entry
- **WHEN** 候选所属项目内没有任何正式 Entry
- **THEN** 系统不调用关系判断，候选关系状态为 `new`

#### Scenario: 不跨项目检索
- **WHEN** 项目内检索相似 Entry
- **THEN** 只检索该候选所属项目的 Entry，不返回其他项目或其他 Workspace 的 Entry

## ADDED Requirements

### Requirement: 相似度阈值规则判定
系统 MUST 使用候选与其 top-1 相似 Entry 的向量相似度阈值规则接管部分关系判定：相似度不低于 `T_high` 时 MUST 直接判定 `duplicate` 并指向该 Entry；相似度不高于 `T_low` 时 MUST 直接判定 `new`；相似度处于 `T_low` 与 `T_high` 之间时 MUST 交由文本模型判定；`supplement` 与 `conflict` MUST 始终由文本模型判定，不得用规则替代。规则直判结果 MUST 仍是候选建议，最终动作由用户确认；目标 Entry 非法时 MUST 降级为 `new`。

#### Scenario: 高相似直判重复
- **WHEN** 候选与 top-1 相似 Entry 的向量相似度不低于 `T_high`
- **THEN** 系统直判 `duplicate` 并指向该 Entry，不调用文本模型

#### Scenario: 低相似直判新建
- **WHEN** 候选与 top-1 相似 Entry 的向量相似度不高于 `T_low`
- **THEN** 系统直判 `new`，不调用文本模型

#### Scenario: 中间区间交 LLM
- **WHEN** 候选与 top-1 相似 Entry 的向量相似度处于 `T_low` 与 `T_high` 之间
- **THEN** 系统交由文本模型判定 `duplicate` / `supplement` / `conflict`

#### Scenario: 目标 Entry 非法降级新建
- **WHEN** 规则直判 `duplicate` 但目标 Entry 不存在或不属于当前项目
- **THEN** 系统将关系状态降级为 `new`
