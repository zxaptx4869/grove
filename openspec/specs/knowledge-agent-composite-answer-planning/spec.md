# knowledge-agent-composite-answer-planning Specification

## Purpose
为 quick 综合回答提供一次受控的复合规划、确定性只读执行、逐项覆盖校验与可恢复快照，同时保持旧协议、范围隔离和人在环上的产品边界。
## Requirements
### Requirement: 旧复合编排退役后保留历史只读结果

系统 MUST 保留复合计划、执行与覆盖快照及既有只读投影，继续遵守现有用户权限与 Workspace 隔离；新 answer Run MUST 使用统一 dialogue-loop，不得再创建、执行或恢复本规格已退役的执行编排。数据库字段与历史迁移 MUST 保持不变。

#### Scenario: 读取退役前记录
- **WHEN** 有权限的用户通过既有读取入口访问复合计划、执行与覆盖快照
- **THEN** 系统继续提供历史数据，不启动旧执行器、不转换或重放旧快照
- **AND** 无权限或跨 Workspace 访问仍按既有合同拒绝
