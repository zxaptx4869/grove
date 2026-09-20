## REMOVED Requirements

### Requirement: 原生端只对明确引用 Entry 提供修订入口
**Reason**: 原生端本轮移除 Entry Revision 发起入口。

**Migration**: Entry 与 Evidence 仍可只读展示；共享后端 Revision 能力保留。


#### Scenario: 从引用详情选择 Entry
- **WHEN** 用户打开一条当前有效 citation 的详情
- **THEN** Sheet 展示明确 Entry 目标和修订动作，不让用户凭“第二条”猜测目标

#### Scenario: 历史引用已失效
- **WHEN** 引用快照可查看但当前 Entry 已删除、移出 Workspace 或无法用于写入
- **THEN** 页面保留历史证据阅读语义，但隐藏或禁用修订动作并说明原因
### Requirement: 修订指令提交清楚表达目标与后果
**Reason**: 原生端不再提交 revision operation Run。

**Migration**: 普通 Composer 始终提交正式只读对话消息。


#### Scenario: 提交修订指令
- **WHEN** 用户输入合法指令并提交
- **THEN** thread 显示“修订《Entry 标题》：指令”或等价可见消息，并显示草稿生成过程

#### Scenario: 输入为空或重复点击
- **WHEN** 指令为空、正在提交或同一 client_message_id 已提交
- **THEN** 主按钮禁用或幂等恢复现有 Run，不生成重复消息或 Draft
### Requirement: 修订草稿与字段差异可编辑可审阅
**Reason**: 原生端移除 Revision Draft 编辑和差异审阅流程。

**Migration**: 不删除共享 Draft 数据、Execution 或后端接口。


#### Scenario: 查看单 Entry 完整差异
- **WHEN** 用户从 draft 卡进入审阅
- **THEN** 页面按改变字段展示操作前与候选值，未改变字段默认不制造差异，并保持 target Entry 和来源可达

#### Scenario: 编辑长正文
- **WHEN** 用户在 360×800、390×844 或 412×915 设备上编辑超过一屏的候选正文
- **THEN** Sheet 可滚动，系统键盘、安全区、输入焦点和主操作按钮不互相遮挡或跳动

#### Scenario: 草稿生成失败
- **WHEN** operation Run 因模型、Evidence 或恢复失败进入 failed
- **THEN** thread 原位显示失败原因与重新生成入口，不展示可确认草稿或成功状态
### Requirement: 确认界面明确修改正式知识
**Reason**: 原生端不再提供正式知识更新确认。

**Migration**: 共享应用服务的人在环确认和并发校验边界保持不变。


#### Scenario: 确认前查看后果
- **WHEN** 用户从差异页选择确认
- **THEN** Sheet 明确说明“将更新 1 条正式知识并追加版本”，同时说明只有未发生后续修改时才能撤销

#### Scenario: Entry 基线过期
- **WHEN** 服务端因 Entry 已被其他操作修改返回 409
- **THEN** 页面保留草稿和用户编辑，显示“知识后来发生了变化”并提供重新生成，不覆盖当前 Entry

#### Scenario: Evidence 失效
- **WHEN** 服务端因来源当前无法核验返回 409
- **THEN** 页面说明需要重新生成或重新阅读，不把历史快照包装成可执行来源
### Requirement: 执行回执与撤销状态可恢复
**Reason**: 原生端不再应用或撤销 Entry Revision。

**Migration**: 数据库中的测试记录不迁移、不删除；其他端的回执与撤销能力不受影响。


#### Scenario: 更新成功回执
- **WHEN** 确认接口返回 applied Execution
- **THEN** thread 显示“正式知识已更新”及真实版本/来源信息，与 AI 草稿状态清楚区分

#### Scenario: 成功撤销
- **WHEN** 用户确认撤销且服务端返回 undone
- **THEN** 原回执收敛为“操作已撤销 · 审计记录保留”，不再提供重复撤销主动作

#### Scenario: 撤销被后续修改阻止
- **WHEN** 服务端返回 Entry 已发生后续修改的 409
- **THEN** 回执保持 applied，显示无法安全撤销及前往桌面版本历史的说明，不宣称恢复成功

#### Scenario: 撤销网络结果未知
- **WHEN** 撤销响应丢失或 App 中途退出
- **THEN** 客户端复用稳定 idempotency key 查询/重试，并从服务端恢复唯一终态
### Requirement: 单 Entry 修订严格对齐移动原型与可访问性基线
**Reason**: 对应原生业务界面整体移除。

**Migration**: 保留仍被对话使用的共享主题和基础 UI，不保留废弃业务组件副本。

## ADDED Requirements

### Requirement: 原生端 Entry 详情保持只读边界
原生 App MUST 仅提供明确 Entry 的当前正文与关联来源阅读，不提供 Entry 修订、差异编辑、确认应用或撤销入口；共享 Revision 服务与其他端调用方不受影响。

#### Scenario: 阅读当前 Entry
- **WHEN** 用户从知识列表打开带明确 Entry 标识的条目
- **THEN** 移动端只调用现有 Entry 只读接口展示当前内容，不出现修订、保存、应用或撤销操作


#### Scenario: 三尺寸与系统能力验收
- **WHEN** 在 360×800、390×844、412×915 及可用 iOS/Android 环境走查完整路径
- **THEN** 顶栏、thread、Composer、键盘、Sheet、全屏差异、底栏和安全区无非预期遮挡/溢出，并保存截图与未验证项

#### Scenario: 原型中的批量内容不抢跑
- **WHEN** 正式页面渲染单 Entry 修订路径
- **THEN** 不出现重复 Entry 标记、冲突对象、多条合并计数或“确认合并”文案
