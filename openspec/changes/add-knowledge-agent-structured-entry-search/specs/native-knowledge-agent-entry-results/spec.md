## ADDED Requirements

### Requirement: 原生对话明确区分综合回答与 Entry 查找结果
原生 App MUST 根据 Run 的实际结果形态渲染综合回答或结构化 Entry 结果；Entry 结果 MUST 使用正式知识对象卡和列表标题，不显示“综合回答”正文或把排序结果标成 Citation。Workspace 范围 MUST 逐项展示项目归属，所有结果保留生成时范围说明。

#### Scenario: 自动返回 Entry 列表
- **WHEN** `actual_result_mode=entries` 的 Run 成功完成
- **THEN** thread 显示“找到 N 条相关知识”及 Entry 卡列表，不先输出一段重复的综合描述

#### Scenario: 自动返回综合回答
- **WHEN** `actual_result_mode=answer`
- **THEN** App 继续使用现有结构化回答、引用、调查摘要与冲突界面，不混入 Entry 结果卡语义

#### Scenario: Workspace 跨项目结果
- **WHEN** 结果来自 Workspace 全部知识且包含多个项目
- **THEN** 每张卡显示项目与目录，列表头不把某一个项目误标为整个结果范围

### Requirement: 用户可以在发送前覆盖结果形态并纠正自动判断
原生 App MUST 在“本次提问设置”中增加 `自动 / 综合回答 / 知识列表` 结果形态选择，并将非自动选择作为可移除 mode chip 展示；设置只作用于下一条消息，发送成功后恢复自动。自动路由结果与用户意图不符时，界面 MUST 提供“改为综合回答 / 列出相关知识”纠正动作；点击后 App 以新的 `client_message_id`、来源 `source_run_id` 和相反的显式 `result_mode` 直接重新提交原问题（用户显式点击发起，不属于后台静默提交），不得修改历史 Run 或复用旧消息标识。服务端 MUST 恢复来源 Run 的原用户消息、生成时范围和输入工作集；原消息未加载、当前范围或当前活动主题变化不得改变纠正语义。

#### Scenario: 显式选择知识列表
- **WHEN** 用户在发送前选择“知识列表”
- **THEN** Composer 显示可移除设置，提交携带 `result_mode=entries`，发送成功后本地选择恢复 `auto`

#### Scenario: 把列表改为综合回答
- **WHEN** 用户在 Entry 结果中点击“改为综合回答”
- **THEN** App 以新的 `client_message_id` 和 `result_mode=answer` 直接重新提交原问题并创建新 Run，历史结果不被修改；对话存在活动 Run 时按冲突提示处理，不产生重复消息

#### Scenario: 把回答改为知识列表
- **WHEN** 用户在合格的综合回答中点击“列出相关知识”
- **THEN** App 以新的 `client_message_id` 和 `result_mode=entries` 直接重新提交原问题并创建新 Run，历史结果不被修改；对话存在活动 Run 时按冲突提示处理，不产生重复消息

#### Scenario: 来源用户消息未加载或当前范围已变化
- **WHEN** 历史卡对应的用户消息不在客户端当前分页，或 Conversation 已切换范围与活动主题
- **THEN** App 仍携带 `source_run_id` 提交，服务端恢复来源 Run 的原问题、范围与输入工作集，不静默无响应，也不改用当前上下文

### Requirement: Entry 结果卡提供稳定扫描信息与当前对象详情
每张结果卡 MUST 展示“正式知识”语义、标题、长度受限摘要、项目/目录、类型、更新时间、来源数量和可用的匹配线索；动态长标题、空目录或跨项目归属 MUST 不造成横向溢出。点击卡片 MUST 打开可滚动详情 Sheet，重新读取当前 Entry，并明确区分结果生成时快照与当前内容。

#### Scenario: 打开仍可用的结果
- **WHEN** 用户点击一张当前仍有权限的 Entry 卡
- **THEN** Sheet 展示当前正式知识完整内容、项目/目录、类型、更新时间与来源摘要，并允许关闭返回原滚动位置

#### Scenario: Entry 已变化
- **WHEN** 当前 Entry 与结果快照的更新时间或内容不同
- **THEN** Sheet 显示当前内容并提示“结果生成后已更新”，历史卡仍保留原快照语义

#### Scenario: Entry 当前不可用
- **WHEN** Entry 已删除、移出当前 Workspace 或权限校验失败
- **THEN** Sheet 显示“该知识当前不可用”，不泄露当前内容，也不在本 change 提供修订动作

### Requirement: 分页、空结果和部分失败在原位可恢复
原生结果列表 MUST 展示当前已加载数量、完整性说明和“加载更多”状态；只有服务端同一快照存在下一页时显示加载更多。loading、empty、partial、error、retry、disabled MUST 保留稳定布局，分页失败只影响下一页且不得清空已加载结果。

#### Scenario: 加载下一页
- **WHEN** 结果响应 `has_more=true` 且用户点击“加载更多”
- **THEN** App 使用原 Run 的不透明游标追加去重结果，按钮进入禁用加载态且不重新提交原问题

#### Scenario: 下一页请求失败
- **WHEN** 已展示首屏结果但下一页网络请求失败
- **THEN** 已有卡片保留，列表底部显示错误与重试，不把整个 Run 改成空或失败

#### Scenario: 结果未承诺穷尽
- **WHEN** 完整性为 `limited` 或 `unknown` 且当前快照已无下一页
- **THEN** 页面明确提示“本次结果可能不完整，可缩小条件再找”，不显示不可执行的无限加载按钮

#### Scenario: 没有找到结果
- **WHEN** Entry 结果集为空
- **THEN** 页面说明当前范围没有找到匹配知识，并提供“修改问题”动作，不显示空白卡或虚假推荐

### Requirement: 原生 Entry 结果严格遵循移动原型与可访问性基线
原生 App MUST 复用当前 Grove 主题、原创 Agent 图标、Card/Sheet/Button、ConversationScreen 和现有键盘避让规则；正式实现 MUST NOT 复制原型 HTML/CSS/静态数据。结果列表、详情 Sheet、模式选择与分页 MUST 在 360×800、390×844、412×915 下无非预期遮挡或横向溢出，纯图标与状态具有辅助名称且不只依赖颜色表达。

#### Scenario: 三尺寸长结果走查
- **WHEN** 三种目标尺寸展示长标题、长摘要、多个项目、分页提示和展开详情
- **THEN** 顶栏、thread、Composer、键盘、Sheet、底栏与安全区不互相遮挡，消息区和详情可独立滚动

#### Scenario: 使用读屏浏览结果
- **WHEN** 用户通过辅助技术访问结果列表
- **THEN** 每张卡读出正式知识、标题、项目/目录和序号，加载更多、纠正模式、关闭和重试具有明确辅助名称与状态

#### Scenario: 多 Entry 操作不抢跑
- **WHEN** 正式页面渲染结构化查找结果
- **THEN** 不出现勾选、全选、批量修订、合并、移动、删除或确认执行文案
