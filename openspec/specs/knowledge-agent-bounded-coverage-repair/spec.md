# knowledge-agent-bounded-coverage-repair Specification

## Purpose
TBD - created by archiving change add-knowledge-agent-bounded-coverage-repair. Update Purpose after archive.
## Requirements
### Requirement: 旧补查退役后保留历史只读结果

系统 MUST 保留补查计划、检查点与结果快照及既有只读投影，继续遵守现有用户权限与 Workspace 隔离；新 answer Run MUST 使用统一 dialogue-loop，不得再创建、执行或恢复本规格已退役的执行编排。数据库字段与历史迁移 MUST 保持不变。

#### Scenario: 读取退役前记录
- **WHEN** 有权限的用户通过既有读取入口访问补查计划、检查点与结果快照
- **THEN** 系统继续提供历史数据，不启动旧执行器、不转换或重放旧快照
- **AND** 无权限或跨 Workspace 访问仍按既有合同拒绝

