## ADDED Requirements

### Requirement: 原生 App 恢复最近对话并支持新建
原生 App MUST 在认证恢复后读取当前用户与 Workspace 的知识对话；存在对话时 MUST 默认打开最近活动对话，不存在或用户选择「新对话」时 MUST 进入本地草稿状态，且 MUST 只在首次发送时按当前范围创建服务端对话。

#### Scenario: 启动恢复最近对话
- **WHEN** 已登录用户启动 App 且当前 Workspace 存在多个知识对话
- **THEN** 对话页打开最近活动对话并恢复其范围、最近消息、活动主题与 Run 状态

#### Scenario: 没有历史对话
- **WHEN** 当前用户在 Workspace 内没有知识对话
- **THEN** 对话页显示可输入的空状态和当前草稿范围，不提前创建服务端空对话

#### Scenario: 新建但未发送
- **WHEN** 用户点击「新对话」后退出页面且未发送消息
- **THEN** 系统不创建服务端 Conversation，历史列表不出现空记录

#### Scenario: 新对话首次发送
- **WHEN** 用户在草稿对话选择范围并首次发送非空问题
- **THEN** 客户端先按该范围创建 Conversation，再向同一 Conversation 提交消息

### Requirement: 对话历史稳定分页与切换
原生 App MUST 显示当前用户的对话历史摘要，并按服务端游标恢复最近消息；初次加载 MUST 渲染最近一页且保持时间正序，用户滚动到顶部时 MUST 向前加载更早消息并按 message_id/run_id 去重，不得跳过、倒序或重复显示。

#### Scenario: 打开历史列表
- **WHEN** 用户打开对话历史 Sheet
- **THEN** 系统按最近活动顺序显示标题、范围、活动主题、最近 Run 状态与时间，并允许切换对话

#### Scenario: 恢复长对话
- **WHEN** 对话消息多于一页
- **THEN** 首屏显示最近消息，用户向上加载后更早页插入顶部且当前阅读位置不突然跳到底部

#### Scenario: 历史页含关联 Run
- **WHEN** 一页消息包含已完成或活动 Run
- **THEN** 客户端使用同页返回的去重 Run 集合恢复结构化回答和状态，而不是逐消息发起 Run 请求

#### Scenario: 历史请求失败
- **WHEN** 对话列表或消息页网络请求失败
- **THEN** 页面保留已知内容并显示就地重试，不把错误渲染为无历史空状态

### Requirement: 范围持续可见且按对话切换
原生对话顶栏 MUST 持续显示当前 Conversation 的 Workspace「全部知识」或具体项目范围；用户选择项 MUST 只有全部知识和当前 Workspace 项目。草稿范围只用于创建参数，既有对话切换 MUST 调用服务端；每个历史回答 MUST 显示生成时范围快照。

#### Scenario: 草稿选择项目范围
- **WHEN** 用户在尚未创建的对话选择当前 Workspace 某项目
- **THEN** 顶栏立即显示该项目的真实名称，首次发送创建项目范围 Conversation

#### Scenario: 既有空闲对话切换范围
- **WHEN** 用户在无活动 Run 的既有对话从项目切换到全部知识
- **THEN** 客户端提交范围变更、刷新对话与消息，并显示服务端范围事件和已失效的旧主题状态

#### Scenario: 选择当前相同范围
- **WHEN** 用户再次选择 Conversation 已有范围
- **THEN** 客户端保持当前状态且服务端不新增范围事件

#### Scenario: 活动 Run 期间切换
- **WHEN** 用户在 waiting/processing Run 期间尝试切换范围
- **THEN** 范围不改变，界面说明需等待或取消当前回答后再切换

#### Scenario: 查看旧范围回答
- **WHEN** 用户切换范围后滚动到更早回答
- **THEN** 回答仍标明其生成时的全部知识或项目范围，不伪装成当前范围结果

### Requirement: 消息提交幂等且可安全重试
原生 App MUST 为每次用户发送生成稳定的 `client_message_id`，去除首尾空白并遵守服务端长度限制；提交结果未知时 MUST 保留 Conversation、文本、模式和同一标识重试，收到确定成功响应后才清除 pending submission。终态失败的重新提问 MUST 使用新标识创建新 Run。

#### Scenario: 正常发送
- **WHEN** 用户输入非空问题并点击发送
- **THEN** 用户消息立即进入待确认发送状态，服务端接受后关联唯一 Run，输入框清空且同一消息不重复

#### Scenario: 提交超时后重试
- **WHEN** 请求可能已到达服务端但客户端未收到响应
- **THEN** 重试复用原 Conversation 和 `client_message_id`，服务端返回首次 Run 而不重复执行

#### Scenario: 活动 Run 冲突
- **WHEN** 发送返回 409 因对话已有活动 Run
- **THEN** 客户端刷新并展示该活动 Run，不创建第二个本地进行中回答

#### Scenario: 终态失败重新提问
- **WHEN** 用户在 failed 回答上选择重新提问
- **THEN** 客户端以相同问题内容和新的 `client_message_id` 创建新 Run，并保留原失败记录

#### Scenario: 空白或过长输入
- **WHEN** 输入为空白或超过服务端最大长度
- **THEN** 发送按钮禁用或显示本地校验，且不创建 Conversation、消息或 Run

### Requirement: 用户可覆盖上下文与回答模式
原生 App MUST 默认按 `context_mode=auto` 与 `answer_mode=auto` 提交，并提供下一条消息的一次性覆盖：继续当前主题、新话题、快速回答、深度查找。非默认选择 MUST 在发送前可见、可移除，成功提交后 MUST 恢复默认。

#### Scenario: 默认自动模式
- **WHEN** 用户不打开模式设置直接发送
- **THEN** 客户端提交两种 `auto` 且不在输入区堆叠模式标签

#### Scenario: 强制深度查找
- **WHEN** 用户选择深度查找后发送下一条消息
- **THEN** 客户端提交 `answer_mode=investigate`，发送前显示该选择，成功后下一条恢复 auto

#### Scenario: 强制继续当前主题
- **WHEN** 用户认为自动判断错误并为下一条选择继续当前主题
- **THEN** 客户端提交 `context_mode=continue`，保留服务端可能要求澄清的结果

#### Scenario: 强制新话题
- **WHEN** 用户为下一条选择新话题
- **THEN** 客户端提交 `context_mode=new_topic`，并在成功后清除该一次性覆盖

### Requirement: 活动 Run 前台轮询并可取消恢复
原生 App MUST 只在 App 前台对 waiting/processing Run 轮询服务端；进入后台 MUST 停止本地轮询但不得取消服务端 Run，恢复前台、重启或重新打开对话时 MUST 立即从服务端恢复。活动 Run MUST 提供取消操作并等待服务端进入取消终态。

#### Scenario: 前台等待回答
- **WHEN** 消息提交返回 waiting 或 processing
- **THEN** 客户端持续轮询同一 Run，更新可验证步骤并在终态自动停止

#### Scenario: 首次轮询已是终态
- **WHEN** 提交后第一次轮询直接返回 completed、failed 或 cancelled
- **THEN** 客户端归并终态消息和回答并清除 activeRun，不保留旧 processing 卡

#### Scenario: App 进入后台
- **WHEN** Run 仍处理且 AppState 离开 active
- **THEN** 客户端停止轮询，服务端 Worker 继续执行且本地不伪装为取消

#### Scenario: 回到前台
- **WHEN** 用户回到 App 或重新打开有活动 Run 的对话
- **THEN** 客户端立即 refetch Run 并从最新服务端状态继续展示

#### Scenario: 用户取消 Run
- **WHEN** 用户确认取消 waiting/processing Run
- **THEN** 客户端提交取消、显示正在取消并轮询到 cancelled，不显示迟到正常回答

#### Scenario: 取消请求失败
- **WHEN** 用户取消 Run 的网络或服务端请求失败
- **THEN** 客户端在 Run 卡保留可见错误、最后已知状态和重试取消操作，不静默吞掉错误

#### Scenario: 取消错误不泄漏到后续 Run
- **WHEN** 某个 Run 的取消请求失败，用户随后切换会话或发起新的 Run
- **THEN** 旧错误不显示在新的活动 Run 卡上，重试取消仅作用于原 Run

#### Scenario: 轮询临时失败
- **WHEN** Run 状态请求网络失败
- **THEN** 客户端保留最后已知状态、停止激进重试并提供手动重试，不重新提交问题

### Requirement: 原生对话状态可访问且不遮挡
原生对话页 MUST 使用安全区、可滚动消息区、真实系统键盘和每个平台唯一的键盘避让负责人；Android `resize` 时 MUST NOT 再以完整 keyboardHeight 补偿 Composer，iOS MUST 使用平台原生避让与安全区。输入聚焦时底栏 MUST 隐藏，composer、长消息、历史 Sheet 和模式 Sheet MUST 在 360×800、390×844、412×915 下可操作且无横向溢出。交互控件 MUST 有辅助名称和非颜色状态表达。

#### Scenario: 键盘展开发送
- **WHEN** 用户在 390×844 设备聚焦多行输入并发送
- **THEN** composer 始终位于键盘上方、底栏隐藏、消息区仍可滚动且发送后焦点行为稳定

#### Scenario: Android resize 不二次跳动
- **WHEN** Android 系统以 resize 展开/收起键盘，或多行 Composer 从一行增至多行
- **THEN** 系统只采用 resize 后可用高度布局，不额外叠加完整键盘高度或动画补偿，最新消息和 Composer 均保持可见

#### Scenario: 小尺寸长对话
- **WHEN** 360×800 设备展示长回答与多个来源
- **THEN** 固定控件不遮挡内容，文字换行且页面不产生水平滚动

#### Scenario: 使用读屏操作
- **WHEN** 用户通过辅助技术访问范围、历史、模式、发送、取消和 Sheet 关闭控件
- **THEN** 每个控件有可理解名称、状态和顺序，不只通过图标或颜色表达
