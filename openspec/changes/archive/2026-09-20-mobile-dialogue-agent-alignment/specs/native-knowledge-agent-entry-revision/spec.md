## ADDED Requirements

### Requirement: 原生端 Entry 详情保持只读边界
原生 App MUST 仅提供明确 Entry 的当前正文与关联来源阅读，不提供 Entry 修订、差异编辑、确认应用或撤销入口；共享 Revision 服务与其他端调用方不受影响。

#### Scenario: 阅读当前 Entry
- **WHEN** 用户从知识列表打开带明确 Entry 标识的条目
- **THEN** 移动端只调用现有 Entry 只读接口展示当前内容，不出现修订、保存、应用或撤销操作

## REMOVED Requirements

### Requirement: 原生端只对明确引用 Entry 提供修订入口
**Reason**: 原生端本轮移除 Entry Revision 发起入口。

**Migration**: Entry 与 Evidence 仍可只读展示；共享后端 Revision 能力保留。

### Requirement: 修订指令提交清楚表达目标与后果
**Reason**: 原生端不再提交 revision operation Run。

**Migration**: 普通 Composer 始终提交正式只读对话消息。

### Requirement: 修订草稿与字段差异可编辑可审阅
**Reason**: 原生端移除 Revision Draft 编辑和差异审阅流程。

**Migration**: 不删除共享 Draft 数据、Execution 或后端接口。

### Requirement: 确认界面明确修改正式知识
**Reason**: 原生端不再提供正式知识更新确认。

**Migration**: 共享应用服务的人在环确认和并发校验边界保持不变。

### Requirement: 执行回执与撤销状态可恢复
**Reason**: 原生端不再应用或撤销 Entry Revision。

**Migration**: 数据库中的测试记录不迁移、不删除；其他端的回执与撤销能力不受影响。

### Requirement: 单 Entry 修订严格对齐移动原型与可访问性基线
**Reason**: 对应原生业务界面整体移除。

**Migration**: 保留仍被对话使用的共享主题和基础 UI，不保留废弃业务组件副本。
