## REMOVED Requirements

### Requirement: 原生回答只在可整理时显示动作
**Reason**: 原生端不再提供固定“整理成知识”入口。

**Migration**: dialogue candidate 块只显示为未应用建议；共享后端 Candidate Draft 能力保留。

### Requirement: Workspace 回答先确认目标项目
**Reason**: 原生端不再发起持久 Candidate Draft，因此不再选择写入项目。

**Migration**: 无数据迁移；现有测试数据保留在数据库。

### Requirement: 草稿生成与历史恢复在对话中可见
**Reason**: 原生当前正式历史只恢复 Conversation、Message、Run 与 dialogue 快照，不恢复旧草稿交互。

**Migration**: 不删除共享 Draft 数据或接口；其他调用方不受影响。

### Requirement: 草稿卡和编辑 Sheet 区分 AI 建议
**Reason**: 原生端移除持久草稿编辑流程。

**Migration**: 普通对话 candidate 块以只读候选语义展示。

### Requirement: 创建 Candidate 前再次明确后果
**Reason**: 原生端不再调用 Candidate 创建写接口。

**Migration**: 共享后端确认服务及其幂等边界保持不变。

### Requirement: 成功回执只表达待确认 Candidate
**Reason**: 原生端不再产生 Candidate 回执或桌面确认台交接。

**Migration**: 已有数据库测试记录不删除，不要求原生端交互兼容。

### Requirement: 候选草稿界面严格对齐移动原型基线
**Reason**: 对应原生业务界面整体移除。

**Migration**: 保留仍被对话使用的共享主题和基础 UI，不保留废弃业务组件副本。

