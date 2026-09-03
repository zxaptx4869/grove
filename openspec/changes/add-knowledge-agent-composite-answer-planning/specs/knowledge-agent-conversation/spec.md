## ADDED Requirements

### Requirement: Conversation 历史恢复复合回答计划与逐项覆盖
Conversation 消息页和 Run 查询 MUST 为新复合 quick Run 返回生成时的可选计划摘要与逐项覆盖快照，至少包含 schema 版本、回答义务的稳定顺序与摘要、实际输入类别、每项终态和依据类别；接口 MUST NOT 返回完整 prompt、模型隐藏推理、完整 Entry/Source 原文或可用于扩大范围的内部参数。范围切换、后续消息、重新打开 App 和历史分页 MUST NOT 重新规划、重新查询或用当前状态改写旧快照。

#### Scenario: 恢复已完成复合回答
- **WHEN** 用户重新打开包含解释、Grove 引用和结构化统计的历史 Conversation
- **THEN** 消息页关联同一 Run 返回原 answer、points、Citation、实际依据、计划摘要和逐项覆盖，内容与生成时快照一致

#### Scenario: 范围切换后查看旧复合回答
- **WHEN** Conversation 从项目范围切换到 Workspace 后读取切换前的复合 Run
- **THEN** 旧回答继续显示生成时范围与覆盖，不把新范围对象、当前统计或后续用户陈述计入旧结果

#### Scenario: 历史分页包含复合与旧 Run
- **WHEN** 同一消息页同时包含有复合快照的新 Run 和没有新增字段的旧 Run
- **THEN** API 对新 Run 返回有界摘要、对旧 Run 返回空复合字段，并保持原有消息顺序、分页和 answer/entries 协议

#### Scenario: 旧客户端忽略复合字段
- **WHEN** 不识别计划摘要和逐项覆盖字段的旧客户端读取新消息页
- **THEN** 它仍能使用现有 answer、points、citations、status、coverage、gaps 和 basis 字段展示结果，不需要重新提交问题

#### Scenario: 计划摘要不泄露内部内容
- **WHEN** 客户端查询复合 Run 或消息历史
- **THEN** 响应只返回可展示义务与状态，不返回原始模型计划、检索 prompt、完整工具参数、未授权对象句柄或隐藏推理
