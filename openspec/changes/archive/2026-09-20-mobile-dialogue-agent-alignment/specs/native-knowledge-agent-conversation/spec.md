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

### Requirement: 用户可覆盖上下文与回答模式
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


#### Scenario: 默认自动模式
- **WHEN** 用户不打开模式设置直接发送
- **THEN** 客户端提交四种 `auto` 且不在输入区堆叠模式标签

#### Scenario: 强制深度查找
- **WHEN** 用户选择深度查找后发送下一条消息
- **THEN** 客户端提交 `answer_mode=investigate`，发送前显示该选择，成功后下一条恢复 auto

#### Scenario: 仅使用我的知识库
- **WHEN** 用户为下一条消息选择“仅使用我的知识库”
- **THEN** Composer 显示可移除的一次性依据 Chip，提交 `basis_mode=knowledge_only`，成功后下一条恢复 auto

#### Scenario: 依据模式网络重试
- **WHEN** `knowledge_only` 消息提交结果未知
- **THEN** 客户端保留原 Conversation、文本、四类模式和 `client_message_id` 重试，不改回 auto 或创建第二条本地消息

#### Scenario: 旧服务端缺少依据能力
- **WHEN** 原生 App 收到不包含 basis 字段的旧响应或服务端明确不接受新字段
- **THEN** 已有对话、回答、范围、上下文和回答模式继续可用，界面不伪造依据记录

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


#### Scenario: 回到前台
- **WHEN** 用户回到 App 或重新打开有活动 Run 的对话
- **THEN** 客户端立即 refetch Run 并从最新服务端状态继续展示
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

### Requirement: 范围持续可见且按对话切换
原生对话页 MUST 在顶部左侧显示不可点击的 G 品牌标识、中间仅显示可点击的当前知识范围文字与轻量下拉箭头、右侧仅显示清晰可辨且可访问的对话历史图标。长项目名 MUST NOT 挤压两侧稳定触控区。历史 Sheet MUST 在顶部提供明显的新建对话入口；范围切换、历史会话切换与新建对话 MUST 实际可用。消息 `context_mode` 设置 MUST NOT 替代或暗示上述会话操作，顶部或 Composer 外 MUST NOT 增加第二个新建入口。

#### Scenario: 打开知识范围
- **WHEN** 用户点击顶部中间的当前知识范围
- **THEN** 页面打开既有范围 Sheet，并可在没有活动 Run 时切换 Workspace 或项目范围

#### Scenario: 打开历史并新建对话
- **WHEN** 用户点击顶部右侧历史入口后选择历史会话或“新建对话”
- **THEN** 页面分别切换到所选 Conversation 或进入新对话草稿，且消息上下文覆盖不参与该操作


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

### Requirement: 对话历史稳定分页与切换
原生 App MUST 在对话页挂载时请求现有全量历史摘要，并在打开历史时复用当前 loading/data/error 状态；MUST NOT 把点击历史误报为网络请求起点。历史列表 MUST 使用不嵌套于同方向 ScrollView 的虚拟列表并限制首批渲染，弹层开关 SHOULD NOT 触发消息树无关重渲染。新建入口 MUST 在首次加载、刷新、空态和失败态持续可用；失败 MUST 可重试，已有列表刷新 MUST NOT 清空闪烁。

#### Scenario: 历史首次加载或失败
- **WHEN** 用户在摘要请求尚未完成或已失败时打开历史 Sheet
- **THEN** Sheet 立即显示顶部新建入口和独立加载或失败重试状态，新建不等待历史返回

#### Scenario: 大量历史摘要
- **WHEN** 全量接口返回大量 Conversation 摘要
- **THEN** 客户端以虚拟列表分批挂载行且不嵌套纵向 ScrollView；本轮不声称减少了网络响应体或 JSON 解析成本


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

### Requirement: 原生 App 恢复最近对话并支持新建
原生 App MUST 区分真正的 App 启动与前后台、栏目往返、弹层开关或页面普通重挂载。没有本账号、本 Workspace 的移动端待恢复工作时，冷启动 MUST 显示沿用最后有效知识范围的空白新对话，并只在首次发送时创建服务端 Conversation。当前进程内的短暂离开 MUST 保留会话、未发送输入和阅读位置，不得按固定闲置时长或模型判断自动切断。

#### Scenario: 无待办冷启动
- **WHEN** 账号和 Workspace 已确认且没有未发送输入、活动/待查看 Run 或结果未知提交记录
- **THEN** 对话首页显示空白新对话，不选择最近已完成历史，也不调用创建 Conversation 接口

#### Scenario: 短暂离开再返回
- **WHEN** 用户切后台、切换其他 App 栏目或打开关闭弹层后返回
- **THEN** 页面保留当前 Conversation 或空白草稿、输入、范围和阅读位置，不重新执行冷启动选择

#### Scenario: 新对话沿用范围
- **WHEN** 用户冷启动进入空白页或从历史 Sheet 手动新建
- **THEN** 页面沿用该身份最后有效的 Workspace/项目范围；项目失权或删除时明确提示并回到 Workspace 范围，不携带旧会话、continuation 或对象绑定


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

## ADDED Requirements

### Requirement: 客户端工作记录按身份隔离并由服务端复验
原生 App MUST 仅持久化恢复所需的 Conversation/Run 引用、范围、未发送输入、稳定提交标识与提交阶段，不持久化第二份消息历史或 Agent 内部快照。记录 MUST 按账号和 Workspace 隔离；退出登录 MUST 清理当前身份记录，身份变化 MUST NOT 读取其他身份记录。恢复 MUST 先完成本地记录读取和现有服务端 API 复验；读取、网络、权限或对象删除失败 MUST 显示可重试或退出状态，不得静默视为无待恢复工作。

#### Scenario: 销毁后恢复未发送输入
- **WHEN** App 在存在非空未发送输入时被销毁并由同一账号/Workspace 重启
- **THEN** 页面恢复原输入、范围及其所属 Conversation 或空白草稿，不创建会话、不发送消息

#### Scenario: 恢复活动或离开期间完成的 Run
- **WHEN** 持久记录指向活动 Run，且重启复验发现其仍活动或已在离开期间完成但尚未展示
- **THEN** 页面恢复所属 Conversation 和服务端最新消息/Run；活动时继续前台轮询，已完成时先展示结果而不是跳到空白页

#### Scenario: 身份或 Workspace 变化
- **WHEN** 登录身份或 Workspace 与工作记录归属不一致，或用户退出登录
- **THEN** 客户端隔离或清理对应记录，不恢复输入、pending、Conversation、Run 或范围到新身份

#### Scenario: 恢复复验失败
- **WHEN** 本地记录读取成功但会话/Run 复验遇到网络、权限变化或对象删除
- **THEN** 页面保留明确恢复错误及重试/退出入口，不自动选择最近历史或创建新会话

### Requirement: 未知提交恢复保持消息幂等且不伪造创建幂等
已有 Conversation 的提交结果未知时，客户端 MUST 保留原目标 Conversation、正文、上下文与 `client_message_id`；恢复后 MUST 先按服务端消息对账，已存在则不得重发，不存在时才允许复用原键重试。创建 Conversation 响应未知时，由于现有接口没有创建幂等键，客户端 MUST NOT 自动再次创建或声称已恢复，MUST 显示无法安全确认的状态和退出路径。

#### Scenario: 已有 Conversation 提交已到达
- **WHEN** 重启后消息页已包含本地 pending 的 `client_message_id`
- **THEN** 客户端清除结果未知状态并恢复该消息/Run，不再次提交

#### Scenario: 已有 Conversation 提交未到达
- **WHEN** 重启对账完成且消息页不含原 `client_message_id`
- **THEN** 客户端提供恢复入口并以同一目标 Conversation 和同一消息键重试

#### Scenario: 创建 Conversation 响应未知
- **WHEN** 首条发送在创建 Conversation 阶段发生网络中断或超时且未得到 Conversation ID
- **THEN** 客户端说明无法安全自动恢复，不重复创建、不发送消息，并允许用户退出到空白新对话

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
