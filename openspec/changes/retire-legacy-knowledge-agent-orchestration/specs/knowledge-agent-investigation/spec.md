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
