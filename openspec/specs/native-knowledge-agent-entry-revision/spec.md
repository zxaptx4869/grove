# native-knowledge-agent-entry-revision Specification

## Purpose
TBD - created by archiving change add-knowledge-agent-entry-revision. Update Purpose after archive.
## Requirements
### Requirement: 原生端只对明确引用 Entry 提供修订入口
原生 App MUST 只在 completed / partial 且含有效 citations 的回答引用详情中，为当前可用 Entry 提供“修订这条知识”动作；动作 MUST 显示 Entry 标题、项目/目录与正式知识语义。insufficient、failed、clarification、cancelled、历史不可用引用和非 Entry 对象 MUST NOT 提供可执行修订入口。

#### Scenario: 从引用详情选择 Entry
- **WHEN** 用户打开一条当前有效 citation 的详情
- **THEN** Sheet 展示明确 Entry 目标和修订动作，不让用户凭“第二条”猜测目标

#### Scenario: 历史引用已失效
- **WHEN** 引用快照可查看但当前 Entry 已删除、移出 Workspace 或无法用于写入
- **THEN** 页面保留历史证据阅读语义，但隐藏或禁用修订动作并说明原因

### Requirement: 修订指令提交清楚表达目标与后果
原生 App MUST 在发起前通过可滚动 Sheet 显示 target Entry、项目/目录、当前摘要和非空指令输入；提交后 MUST 在 thread 中追加可见用户消息并恢复同一 operation Run。普通 Composer 消息 MUST 继续是只读问答。

#### Scenario: 提交修订指令
- **WHEN** 用户输入合法指令并提交
- **THEN** thread 显示“修订《Entry 标题》：指令”或等价可见消息，并显示草稿生成过程

#### Scenario: 输入为空或重复点击
- **WHEN** 指令为空、正在提交或同一 client_message_id 已提交
- **THEN** 主按钮禁用或幂等恢复现有 Run，不生成重复消息或 Draft

### Requirement: 修订草稿与字段差异可编辑可审阅
原生 App MUST 将 generating、draft、failed、cancelled 与终态 Revision Draft 归并到对应消息；draft 卡 MUST 标识“AI 建议 · 待确认”、target Entry、项目/目录、变更字段与来源数量，并提供“编辑并检查”。编辑使用适配系统键盘的 Sheet，完整差异使用可滚动全屏审阅，差异内容来自服务端而非客户端自行猜测。

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
原生 App MUST 在最终确认 Sheet 中显示目标 Entry、项目/目录、变化字段数、新增来源数、版本与撤销边界，并明确主按钮会更新一条正式知识。确认中 MUST 禁止重复提交，未知结果重试 MUST 复用 client_operation_id。

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
原生 App MUST 在应用成功后显示持久回执，包含正式 Entry、版本、变化摘要、来源增量、操作时间/标识、查看 Entry/差异和撤销动作；撤销必须二次确认。重启或历史恢复 MUST 按服务端 Execution/Draft 状态显示 applied、undoing、undone 或冲突，不使用本地乐观状态冒充成功。

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
原生修订路径 MUST 复用 Grove 当前主题、原创 Agent 图标和现有对话组件，按移动原型的草稿、差异、确认、回执与撤销信息层级实现；MUST NOT 复制原型 HTML/CSS/演示数据或显示本 change 未实现的多 Entry 合并。所有纯图标动作、状态、全屏层与 Sheet MUST 具备可访问名称、返回/关闭、焦点恢复和不只依赖颜色的语义。

#### Scenario: 三尺寸与系统能力验收
- **WHEN** 在 360×800、390×844、412×915 及可用 iOS/Android 环境走查完整路径
- **THEN** 顶栏、thread、Composer、键盘、Sheet、全屏差异、底栏和安全区无非预期遮挡/溢出，并保存截图与未验证项

#### Scenario: 原型中的批量内容不抢跑
- **WHEN** 正式页面渲染单 Entry 修订路径
- **THEN** 不出现重复 Entry 标记、冲突对象、多条合并计数或“确认合并”文案

