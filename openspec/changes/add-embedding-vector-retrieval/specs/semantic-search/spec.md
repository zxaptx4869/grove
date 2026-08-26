## RENAMED Requirements

- FROM: `### Requirement: 确定性候选召回`
- TO: `### Requirement: 混合候选召回`

## MODIFIED Requirements

### Requirement: 混合候选召回
系统 MUST 在语义重排前，基于查询与 Entry 标题、核心内容、目录节点名称及来源标题的关键词与字符重叠做确定性召回，并合并当前 Workspace 与所选范围内已确认 Entry 的 embedding 向量召回，形成候选集；候选集 MUST 限定在当前 Workspace 与所选范围内；embedding 未配置、调用失败或无可用向量时 MUST 降级为仅确定性召回并明确标记，不得静默中断。

#### Scenario: 生成混合候选集
- **WHEN** 用户输入自然语言查询且 embedding 可用
- **THEN** 系统返回确定性召回与 embedding 召回去重合并后的候选 Entry 集合，供语义重排使用

#### Scenario: embedding 降级为确定性召回
- **WHEN** 当前 Workspace 未配置 embedding 或编码失败
- **THEN** 系统返回确定性召回候选集并明确标记降级，不调用外部服务

#### Scenario: 候选集限定范围
- **WHEN** 用户在项目内或全局发起语义搜索
- **THEN** 混合候选集只包含该项目内或当前 Workspace 全部项目的已确认 Entry
