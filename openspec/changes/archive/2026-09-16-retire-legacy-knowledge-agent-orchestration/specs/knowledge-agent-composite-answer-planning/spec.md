## REMOVED Requirements

### Requirement: 复合计划从原始请求形成有界回答义务
**Reason**: 旧 composite planner 随 runner 退役。
**Migration**: 新 Run 使用统一 dialogue-loop；历史计划继续投影读取。

### Requirement: 模型计划只是候选且由服务端严格规范化
**Reason**: 旧 composite planner 不再生成计划。
**Migration**: 统一循环的候选-only、权限和工具参数校验保持不变。

### Requirement: quick 复合回答使用固定的一次受控执行图
**Reason**: 旧 quick 复合执行图退役。
**Migration**: 新 Run 只执行统一 dialogue-loop。

### Requirement: 结构化工具数值形成服务端事实而非模型数字
**Reason**: 该要求绑定旧 composite 执行物化流程。
**Migration**: 统一循环仍只能采用现行只读工具返回的结构化事实。

### Requirement: 最终综合按回答义务逐项校验覆盖
**Reason**: 旧 composite coverage 模型退役。
**Migration**: 不将历史 coverage 转换为统一循环状态。

### Requirement: 复合回答计划、执行和覆盖可恢复且可观测
**Reason**: 旧 composite 检查点不再恢复。
**Migration**: 历史计划、执行与 coverage 字段继续只读；旧 processing Run 失败收尾。

### Requirement: 复合回答保持协议兼容且没有写入副作用
**Reason**: 新 Run 不再生成旧 composite 协议对象。
**Migration**: 公开响应字段和历史投影保留；统一循环继续候选-only。

### Requirement: 首次 coverage 可以触发一次受控缺口补查
**Reason**: 旧 coverage repair 入口退役。
**Migration**: 不对历史 coverage 启动补查。

## ADDED Requirements

### Requirement: 旧复合编排退役后保留历史只读结果

系统 MUST 保留复合计划、执行与覆盖快照及既有只读投影，继续遵守现有用户权限与 Workspace 隔离；新 answer Run MUST 使用统一 dialogue-loop，不得再创建、执行或恢复本规格已退役的执行编排。数据库字段与历史迁移 MUST 保持不变。

#### Scenario: 读取退役前记录
- **WHEN** 有权限的用户通过既有读取入口访问复合计划、执行与覆盖快照
- **THEN** 系统继续提供历史数据，不启动旧执行器、不转换或重放旧快照
- **AND** 无权限或跨 Workspace 访问仍按既有合同拒绝
