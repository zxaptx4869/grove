## REMOVED Requirements

### Requirement: 补查统计保持口径且失败展示不丢失确定性事实
**Reason**: 旧 coverage repair 执行器退役。
**Migration**: 历史补查结果继续只读。

### Requirement: 回答质量修复保持真实状态和依据
**Reason**: 旧 coverage repair 不再修改 answer 状态。
**Migration**: 统一循环按现行状态和依据合同收尾。

### Requirement: 只有真实且可修复的逐项缺口进入一次补查
**Reason**: 旧缺口补查入口退役。
**Migration**: 新 Run 不生成旧 repair plan。

### Requirement: 补查计划是闭合模型候选并由服务端规范化
**Reason**: 旧 repair planner 退役。
**Migration**: 历史 plan 字段保持可空可读。

### Requirement: 补查在任何工具前固化独立总预算
**Reason**: 旧 repair 执行预算不再使用。
**Migration**: 统一循环使用现行预算合同。

### Requirement: 补查只执行新请求并复用已提交结果
**Reason**: 旧 repair 执行与复用逻辑退役。
**Migration**: 不恢复或转换历史 repair 请求。

### Requirement: 补查失败保留首次合法回答并诚实收尾
**Reason**: 新 Run 不进入旧 repair 阶段。
**Migration**: 统一循环按现行失败和部分完成规则收尾。

### Requirement: 补查支持取消、检查点、Worker 恢复和幂等重放
**Reason**: 旧 repair 检查点不再恢复。
**Migration**: 旧 processing 快照明确失败；历史字段只读。

### Requirement: 补查保持 Run 范围隔离、可观测和无写入副作用
**Reason**: 旧 repair 执行器不再运行。
**Migration**: 统一循环继续遵守 Workspace、可观测和只读工具边界。
