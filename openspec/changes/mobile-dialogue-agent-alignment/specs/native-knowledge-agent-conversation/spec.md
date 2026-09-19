## MODIFIED Requirements

### Requirement: 消息提交幂等且可安全重试
原生 App MUST 为每次用户发送生成稳定的 `client_message_id`，去除首尾空白并遵守服务端长度限制；提交结果未知时 MUST 保留 Conversation、文本、受支持的上下文设置和同一标识重试，收到确定成功响应后才清除 pending submission。continuation MUST 以新的正式消息和新标识提交；终态失败的重新提问也 MUST 使用新标识创建新 Run。

#### Scenario: 正常发送
- **WHEN** 用户输入非空问题并点击发送
- **THEN** 用户消息立即进入普通发送中状态且不能重复发送或恢复，不显示结果未知警告；服务端接受后关联唯一 Run，输入框清空且同一消息不重复

#### Scenario: 提交超时后重试
- **WHEN** 请求可能已到达服务端但客户端未收到响应
- **THEN** 页面持久显示结果未知与恢复入口；重试复用原 Conversation、原问题、原上下文设置和 `client_message_id`，重试进行中禁用重复操作，服务端返回首次 Run 而不重复执行

#### Scenario: 活动 Run 冲突
- **WHEN** 发送返回 409 因对话已有活动 Run
- **THEN** 客户端按确定性拒绝刷新并展示该活动 Run，不显示结果未知恢复入口，也不创建第二个本地进行中回答

#### Scenario: 服务端确定性拒绝
- **WHEN** 提交收到鉴权、校验、冲突或服务端失败等明确 HTTP 响应
- **THEN** 客户端结束发送中状态并显示对应错误，不把该响应伪装成网络结果未知；再次发送使用新的 `client_message_id`

#### Scenario: continuation 提交
- **WHEN** 当前 Conversation 的服务端终态 Run 明确返回 `can_continue=true` 且用户点击继续
- **THEN** 客户端在同一 Conversation 提交一条新的正式“继续”消息并使用新的 `client_message_id`，不复用结果未知提交的标识，也不拼装内部 continuation

#### Scenario: 终态失败重新提问
- **WHEN** 用户在 failed 回答上选择重新提问
- **THEN** 客户端以相同问题内容和新的 `client_message_id` 创建新 Run，并保留原失败记录

#### Scenario: 空白或过长输入
- **WHEN** 输入为空白或超过服务端最大长度
- **THEN** 发送按钮禁用或显示本地校验，且不创建 Conversation、消息或 Run

### Requirement: 用户只可覆盖正式 Agent 支持的上下文行为
原生 App MUST 默认按 `context_mode=auto` 提交，并只提供服务端正式支持且语义准确的“继续当前主题”和“新话题”一次性覆盖；非默认选择 MUST 在发送前可见、可移除，成功提交后 MUST 恢复默认，提交结果未知的重试 MUST 复用原选择和同一 `client_message_id`。原生 App MUST NOT 提供快速/深度、强制结果形式、依据模式或旧结果纠正入口，也 MUST NOT 为保留控件改变 Agent 路由、提示词或执行规则。

#### Scenario: 默认自动上下文
- **WHEN** 用户不打开上下文设置直接发送
- **THEN** 客户端提交 `context_mode=auto` 且输入区不显示设置标签

#### Scenario: 强制继续当前主题
- **WHEN** 用户为下一条消息选择继续当前主题
- **THEN** 客户端提交 `context_mode=continue`，保留服务端可能要求澄清或拒绝续接的结果

#### Scenario: 强制新话题
- **WHEN** 用户为下一条消息选择新话题
- **THEN** 客户端提交 `context_mode=new_topic`，并在确定成功后清除该一次性覆盖

#### Scenario: 上下文设置结果未知
- **WHEN** 非默认上下文消息提交结果未知
- **THEN** 客户端保留原 Conversation、文本、上下文模式和 `client_message_id` 重试，不恢复 auto 或创建第二条本地消息

#### Scenario: 不再展示废弃设置
- **WHEN** 用户打开本次提问设置
- **THEN** 页面不存在快速/深度、综合回答/知识列表、仅知识库或旧结果纠正选项

### Requirement: 活动 Run 前台轮询并可取消恢复
原生 App MUST 只在 App 前台对 waiting/processing Run 轮询服务端；进入后台 MUST 停止本地轮询但不得取消服务端 Run，恢复前台、重启或重新打开对话时 MUST 立即从服务端恢复。活动 Run MUST 提供取消操作并等待服务端进入取消终态；终态 Run MUST 停止轮询并以服务端 `dialogue_loop_status`、`dialogue_stage`、`dialogue_blocks` 和 `can_continue` 为正式显示状态。

#### Scenario: 前台等待回答
- **WHEN** 消息提交返回 waiting 或 processing
- **THEN** 客户端持续轮询同一 Run，更新服务端真实阶段并在终态自动停止

#### Scenario: 首次轮询已是终态
- **WHEN** 提交后第一次轮询直接返回 completed、partial、failed、cancelled、not_executed 或 unsupported
- **THEN** 客户端归并终态消息和结构化结果并清除 activeRun，不保留旧 processing 卡

#### Scenario: App 进入后台
- **WHEN** Run 仍处理且 AppState 离开 active
- **THEN** 客户端停止轮询，服务端 Worker 继续执行且本地不伪装为取消或失败

#### Scenario: 回到前台或重启
- **WHEN** 用户回到 App 或重新打开有活动或已终态 Run 的对话
- **THEN** 客户端立即从服务端恢复最新 Run 和 dialogue 快照，不依赖本地草稿、旧引用或操作状态

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
- **THEN** 客户端保留最后已知服务端状态并提供手动重试，不把 Run 改成本地 failed/cancelled，也不重新提交问题

### Requirement: 原生对话状态可访问且不遮挡
原生对话页 MUST 使用安全区、可滚动消息区、真实系统键盘和每个平台唯一的键盘避让负责人；Android `resize` 时 MUST NOT 再以完整 keyboardHeight 补偿 Composer，iOS MUST 使用平台原生避让与安全区。输入聚焦时底栏 MUST 隐藏，composer、长消息、历史 Sheet 和上下文设置 Sheet MUST 在 360×800、390×844、412×915 下可操作且无横向溢出。交互控件 MUST 有辅助名称和非颜色状态表达。

#### Scenario: 键盘展开发送
- **WHEN** 用户在 390×844 设备聚焦多行输入并发送
- **THEN** composer 始终位于键盘上方、底栏隐藏、消息区仍可滚动且发送后焦点行为稳定

#### Scenario: Android resize 不二次跳动
- **WHEN** Android 系统以 resize 展开/收起键盘，或多行 Composer 从一行增至多行
- **THEN** 系统只采用 resize 后可用高度布局，不额外叠加完整键盘高度或动画补偿，最新消息和 Composer 均保持可见

#### Scenario: 小尺寸长对话
- **WHEN** 360×800 设备展示长回答、知识列表和底部详情正文
- **THEN** 固定控件不遮挡内容，文字换行且页面不产生水平滚动

#### Scenario: 使用读屏操作
- **WHEN** 用户通过辅助技术访问范围、历史、上下文设置、发送、继续、取消和正文展开控件
- **THEN** 每个控件有可理解名称、状态和顺序，不只通过图标或颜色表达

### Requirement: 顶部入口保持品牌、范围与会话职责
原生对话页 MUST 在顶部左侧显示不可点击的 G 品牌标识、中间显示可点击的当前知识范围、右侧显示清晰可辨且可访问的对话历史入口。历史 Sheet MUST 提供明显的新建对话入口；范围切换、历史会话切换与新建对话 MUST 实际可用。消息 `context_mode` 设置 MUST NOT 替代或暗示上述会话操作。

#### Scenario: 打开知识范围
- **WHEN** 用户点击顶部中间的当前知识范围
- **THEN** 页面打开既有范围 Sheet，并可在没有活动 Run 时切换 Workspace 或项目范围

#### Scenario: 打开历史并新建对话
- **WHEN** 用户点击顶部右侧历史入口后选择历史会话或“新建对话”
- **THEN** 页面分别切换到所选 Conversation 或进入新对话草稿，且消息上下文覆盖不参与该操作

### Requirement: 对话初始定位与历史阅读互不干扰
原生 App MUST 在首次进入对话页和显式切换历史 Conversation 后，于最新消息数据和内容布局就绪时为该会话执行一次必要的底部定位。轮询、前后台切换、关闭详情或普通重渲染 MUST NOT 反复强制定位；用户上滑或加载更早历史时 MUST 保留阅读位置。发送新问题后 MUST 让本次发送反馈可见。

#### Scenario: 首次进入或切换会话
- **WHEN** 当前 Conversation 的最新消息读取完成且消息内容完成布局
- **THEN** 页面无动画定位到最新消息，且该会话后续轮询不重复触发初始定位

#### Scenario: 主动阅读历史
- **WHEN** 用户已上滑或加载更早消息
- **THEN** 新增旧页、轮询更新、打开并关闭 Entry 详情或短暂切后台不会把页面强制拉到底部

#### Scenario: 发送新问题
- **WHEN** 用户从输入区发送新的问题
- **THEN** 页面跟随到本次用户消息发送态或后续 Run 反馈，而不要求用户手动滚到底部

## ADDED Requirements

### Requirement: continuation 只续接当前对话的可恢复任务
原生 App MUST 只根据当前 Conversation 已恢复的服务端 Run 提供继续入口，且 MUST 让入口与具体 Run 的终态卡绑定；客户端 MUST NOT 使用其他 Conversation、其他历史 Run 或本地缓存的 continuation 续接任务。

#### Scenario: 当前终态可继续
- **WHEN** 当前 Conversation 的最新可恢复 Run 返回 `can_continue=true`
- **THEN** 对应终态卡显示继续入口，提交后服务端决定恢复的内部步骤

#### Scenario: 切换会话
- **WHEN** 用户从可继续的 Conversation 切换到另一 Conversation
- **THEN** 原继续入口不作用于新 Conversation，新页面只显示该 Conversation 服务端返回的可继续状态

#### Scenario: 旧历史 Run 不再可继续
- **WHEN** 历史 Run 曾可继续但当前服务端响应为 `can_continue=false` 或已有更新 Run
- **THEN** 客户端不根据旧缓存显示或执行继续
