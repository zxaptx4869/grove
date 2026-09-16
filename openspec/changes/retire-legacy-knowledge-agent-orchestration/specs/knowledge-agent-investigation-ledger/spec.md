## REMOVED Requirements

### Requirement: 调查账本归属当前 Run 且隔离
**Reason**: 新 Run 不再创建旧 investigation 账本。
**Migration**: 历史账本及其 Workspace 过滤 API 继续只读保留。

### Requirement: 轮次与查询过程完整留痕
**Reason**: 旧 investigation 轮次执行器退役。
**Migration**: 历史轮次与查询表不删除；统一循环使用自身工具审计。

### Requirement: 已发现集合跨轮次去重并可重建
**Reason**: 旧 investigation 恢复逻辑退役。
**Migration**: 历史集合不重建、不转换为统一循环状态。

### Requirement: 账本事实只能来自当前 Run Evidence
**Reason**: 新 Run 不再写入旧账本。
**Migration**: 统一循环继续执行现行 Evidence 与来源边界。

### Requirement: 账本内容紧凑且不是正式知识
**Reason**: 新 Run 不再生成旧账本内容。
**Migration**: 历史账本仍不是正式 Entry，保持只读。

### Requirement: 候选分配可恢复且可审计
**Reason**: 旧 investigation 候选池执行状态不再恢复。
**Migration**: 历史审计数据保留；不自动重放或转换。
