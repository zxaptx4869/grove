## REMOVED Requirements

### Requirement: 服务端将复合计划编译为受限共享执行图
**Reason**: 旧共享执行图编译器退役。
**Migration**: 新 Run 不生成图；历史图字段继续只读。

### Requirement: 等价数据集与输出节点只执行一次
**Reason**: 旧图节点调度器退役。
**Migration**: 统一循环按现行工具执行合同运行。

### Requirement: 图结构与总预算在执行前严格校验
**Reason**: 旧共享图不再执行。
**Migration**: 统一循环继续使用现行预算与工具参数校验。

### Requirement: 调度器确定性执行依赖并只安全并行
**Reason**: 旧图调度器退役。
**Migration**: 不迁移图依赖或并发状态。

### Requirement: 节点检查点可恢复且终态不可自动重试
**Reason**: 旧图节点检查点不再恢复。
**Migration**: 历史图只读；旧 processing Run 明确失败。

### Requirement: 共享图物化兼容结果并完整记录实际执行
**Reason**: 新 Run 不再物化旧图结果。
**Migration**: 历史结果和可观测记录继续读取。

### Requirement: 补查只扩展严格新增的共享只读节点
**Reason**: 旧共享图 coverage 扩展退役。
**Migration**: 不恢复或扩展历史图。

## ADDED Requirements

### Requirement: 旧共享图退役后保留历史只读快照

系统 MUST 保留共享图与节点执行快照及既有只读投影，继续遵守现有用户权限与 Workspace 隔离；新 answer Run MUST 使用统一 dialogue-loop，不得再创建、执行或恢复本规格已退役的执行编排。数据库字段与历史迁移 MUST 保持不变。

#### Scenario: 读取退役前记录
- **WHEN** 有权限的用户通过既有读取入口访问共享图与节点执行快照
- **THEN** 系统继续提供历史数据，不启动旧执行器、不转换或重放旧快照
- **AND** 无权限或跨 Workspace 访问仍按既有合同拒绝
