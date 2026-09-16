## REMOVED Requirements

### Requirement: 回答模式可选择且可追溯
**Reason**: 旧 quick/investigate answer 路由随 runner 退役。
**Migration**: 新 answer Run 使用统一 dialogue-loop；历史模式字段继续只读。

### Requirement: 调查控制器只提出结构化下一步
**Reason**: 旧 investigation 控制器不再执行。
**Migration**: 不迁移旧控制器状态到统一循环。

### Requirement: 调查受服务端硬预算约束
**Reason**: 旧 investigation 执行预算不再用于新 Run。
**Migration**: 新 Run 使用统一 dialogue-loop 的既有预算合同。

### Requirement: 无进展与重复查询确定性停止
**Reason**: 旧 investigation 轮次调度不再执行。
**Migration**: 新 Run 使用统一 dialogue-loop 的既有停止规则。

### Requirement: 调查轮次可恢复且可取消
**Reason**: 旧 investigation 轮次不再恢复。
**Migration**: 历史轮次保留只读；旧 processing 快照明确失败收尾。

### Requirement: 调查停止结果对用户可解释
**Reason**: 旧 investigation 终态生成器不再执行。
**Migration**: 历史调查摘要继续通过现有 API 读取。

### Requirement: 深度查找必须执行真实 Grove 调查并遵守依据限制
**Reason**: 旧独立 investigate 模式退役。
**Migration**: 统一 dialogue-loop 继续通过现行 Grove 只读工具、来源边界和候选-only 合同回答。

## ADDED Requirements

### Requirement: 旧调查执行退役后保留历史只读详情

系统 MUST 保留调查摘要、详情及关联历史记录及既有只读投影，继续遵守现有用户权限与 Workspace 隔离；新 answer Run MUST 使用统一 dialogue-loop，不得再创建、执行或恢复本规格已退役的执行编排。数据库字段与历史迁移 MUST 保持不变。

#### Scenario: 读取退役前记录
- **WHEN** 有权限的用户通过既有读取入口访问调查摘要、详情及关联历史记录
- **THEN** 系统继续提供历史数据，不启动旧执行器、不转换或重放旧快照
- **AND** 无权限或跨 Workspace 访问仍按既有合同拒绝
