## MODIFIED Requirements

### Requirement: Run 过程只展示可验证阶段
原生 App MUST 以服务端 `dialogue_stage` 和 `dialogue_loop_status` 展示准备、检索知识、读取 Entry、核验证据、综合回答等用户可验证状态；`current_step` 只能用于旧响应回退。客户端 MUST NOT 展示隐藏推理、内部 continuation、控制器理由或与服务端无关的伪进度，且任一终态 MUST 停止进行中动效。

#### Scenario: 正式 Run 处理中
- **WHEN** `dialogue_loop_status` 为 waiting 或 processing 且存在已知 `dialogue_stage`
- **THEN** Agent 标识附近以紧凑过程行显示一次真实阶段和轻量中性取消入口，不重复显示范围或使用大面积阴影卡

#### Scenario: quick Run 处理中
- **WHEN** quick Run 正在搜索或读取证据
- **THEN** 过程卡显示对应可验证动作和生成时范围，并提供取消，不编造详细思考步骤

#### Scenario: 调查进行到第二轮
- **WHEN** investigate Run 的 `current_round=2` 且仍 processing
- **THEN** 过程卡显示深度查找和当前轮次，不能显示超过服务端预算的虚假总进度

#### Scenario: 步骤未知
- **WHEN** 客户端收到未识别的 future `dialogue_stage`
- **THEN** 使用稳定的“正在处理”通用文案且继续轮询，不崩溃或暴露原始枚举

#### Scenario: Run 终态
- **WHEN** `dialogue_loop_status` 进入 completed、partial、failed、cancelled、not_executed 或 unsupported
- **THEN** 过程卡转为对应持久终态，不继续显示“正在处理”或进行中动效

#### Scenario: 取消进行中
- **WHEN** 用户已点击活动 Run 的取消入口且请求尚未完成
- **THEN** 取消入口保持至少 44×44 触控尺寸、显示正在取消并禁止重复操作，阶段区不显示伪进度

#### Scenario: 取消请求失败
- **WHEN** 取消请求网络失败或服务端拒绝
- **THEN** 紧凑过程区保留最后已知真实阶段并显示可见失败信息，用户仍可按现有语义重试取消

### Requirement: 结构化回答状态清晰区分
原生 App MUST 以 `dialogue_loop_status` 结合 Run 状态区分 completed、partial、failed、cancelled、not_executed 和 unsupported，并从正式 `dialogue_blocks` 展示 insufficient 或 candidate 等内容语义。AI 即时回答 MUST 标识为即时结果，不得因存在 Entry 或 Evidence 就把整段回答默认标为“基于正式知识”，也不得显示为正式 Entry。

#### Scenario: 完成回答
- **WHEN** dialogue 状态为 completed 且存在可展示块
- **THEN** 页面按块顺序显示即时结果、范围和实际块语义，不追加重复扁平答案

#### Scenario: 部分完成
- **WHEN** dialogue 状态为 partial 且仍有已交付块
- **THEN** 页面保留已交付内容并在内容附近说明结果未完整完成

#### Scenario: 知识不足块
- **WHEN** 结果包含 insufficient 块
- **THEN** 页面显示服务端提供的不足说明和下一步提示，不用成功完成文案掩盖不足

#### Scenario: 失败、取消、未执行或不支持
- **WHEN** dialogue 状态为 failed、cancelled、not_executed 或 unsupported
- **THEN** 页面显示对应持久状态和适用恢复动作，不伪造回答内容


#### Scenario: 正常带引用回答
- **WHEN** answer 为 completed 且有有效 citations，basis 只包含 Grove
- **THEN** 页面展示回答正文、生成时范围、来源条与“基于你的知识”依据语义

#### Scenario: 正常无引用回答
- **WHEN** answer 为 completed、citations 为空且 basis 合法标记模型通用知识或用户陈述
- **THEN** 页面展示正常即时回答和实际依据，不因为没有 Citation 显示知识不足或“基于正式知识”

#### Scenario: 部分回答
- **WHEN** answer 为 partial 且仍有有效内容
- **THEN** 页面保留有效回答、实际依据和可用引用，并在内容附近说明哪些部分降级、失效或未覆盖

#### Scenario: 知识不足
- **WHEN** answer.status 为 insufficient，无论 quick Run 是 completed 还是调查 Run 是 partial
- **THEN** 页面统一显示依据不足语义、`insufficient_note` 和可用 gaps，不使用成功完成文案掩盖不足

#### Scenario: 澄清回答
- **WHEN** answer.status 为 clarification
- **THEN** 页面显示需要用户补充的信息并允许在同一 Conversation 继续回复，不把它当失败或事实答案

#### Scenario: 回答失败
- **WHEN** answer.status 为 failed 或 Run 为 failed
- **THEN** 页面显示持久错误、已知原因和重新提问操作，不用 toast 代替可恢复状态
### Requirement: 降级、取消与网络错误有稳定恢复
原生 App MUST 保留服务端已交付的有效块并表达 partial 或失败边界；cancelled、not_executed、unsupported、请求错误和服务端 failed MUST 使用彼此可区分的持久状态。客户端 MUST NOT 默认暴露 provider、model、堆栈或原始错误，也 MUST NOT 把移动网络错误改写成服务端执行失败。

#### Scenario: 部分块已交付
- **WHEN** dialogue 状态为 partial 且包含有效块
- **THEN** 页面保留有效块、标记未完整完成，并按服务端状态决定是否显示继续

#### Scenario: 用户取消
- **WHEN** Run 终态为 cancelled
- **THEN** 页面显示已取消且不继续播放处理动画

#### Scenario: 未执行或不支持
- **WHEN** dialogue 状态为 not_executed 或 unsupported
- **THEN** 页面分别说明任务未执行或当前不支持，不伪装为知识不足或网络失败

#### Scenario: 网络不可用
- **WHEN** 仅移动网络请求失败且服务端 Run 状态未知
- **THEN** 页面显示连接问题和刷新动作，保留最后已知内容，不把 Run 改成本地 failed/cancelled

#### Scenario: 失败后重新提问
- **WHEN** 用户在 failed 终态选择重新提问
- **THEN** 客户端以原问题和新的 `client_message_id` 创建新 Run，旧失败记录保持不变


#### Scenario: auto 路由降级到 quick
- **WHEN** Run 实际模式为 quick 且 fallback 表示回答模式路由不可用
- **THEN** 页面说明已改用快速回答并保留回答，不伪装成按计划完成深度查找

#### Scenario: 工具部分失败
- **WHEN** fallback_summary 显示部分检索或证据步骤失败但仍有有效回答
- **THEN** 页面标记部分结果并保留有效引用，提供重试但不隐藏失败范围

#### Scenario: partial 或可恢复降级
- **WHEN** answer.status 为 partial，或 fallback_summary 指示已有有效结果但可通过新 Run 补查
- **THEN** 页面提供重新提问或适配的恢复入口，不自行把 insufficient 改写为 partial

#### Scenario: partial 或 fallback 重新提问
- **WHEN** 用户从 partial 或带可恢复 fallback 的回答选择重新提问
- **THEN** 客户端以原问题创建新的 Run，并保留旧回答和旧引用快照
### Requirement: 长内容 Sheet 可滚动且恢复对话
原生 App MUST 让 History、Scope、上下文设置与 Entry 详情 Sheet 的长内容在 Sheet 内独立滚动；关闭任何 Sheet 后 MUST 保留对话阅读状态。长项目名、正文、错误或选项列表不得遮挡关闭、重试或 Composer。

#### Scenario: 长 Entry 正文
- **WHEN** 用户在底部详情中阅读超过一屏的当前 Entry 正文
- **THEN** 正文在详情 Sheet 内以正常阅读字号和行距滚动，关闭、遮罩、系统返回和安全区可用，关闭后主对话保持原阅读位置

#### Scenario: 长历史或选项
- **WHEN** History、Scope 或上下文设置列表超过可用高度
- **THEN** 对应 Sheet 内可滚动，关闭后对话仍保留原消息位置和输入状态

#### Scenario: 长引用原文
- **WHEN** Citation quote 或 Source 标题超过一屏
- **THEN** 用户可在 Citation Sheet 内滚动到全部内容并始终可关闭 Sheet

## ADDED Requirements

### Requirement: 正式回答按 dialogue blocks 原序渲染
原生 App MUST 按服务端数组原序渲染 `text`、`list`、`statistic`、`entry`、`evidence`、`candidate` 与 `insufficient` 块，并保持列表项顺序和服务端编号语义。存在可展示块时 MUST NOT 再显示完整扁平 `answer`；没有结构化块时 MAY 显示简单文本回退。未知块或单块字段异常 MUST 安全降级并保留同轮其他块，不得伪造字段、解析自然语言补元数据或静默丢掉整轮回答。

#### Scenario: 混合块回答
- **WHEN** 一轮结果按 text、list、statistic、candidate 顺序交付
- **THEN** 页面按相同顺序展示一次，不按客户端类型重新分组，也不追加完整扁平答案

#### Scenario: 列表顺序
- **WHEN** list 块包含多项并由服务端给定顺序或序号
- **THEN** 客户端保持原序和位置参照，“第一条、第二条”不会因渲染排序改变

#### Scenario: 缺少结构化结果
- **WHEN** 历史 Run 或异常响应没有可展示的 dialogue blocks 但有非空扁平 answer
- **THEN** 页面只显示简洁文本回退，不重建旧 points、citations 或依据概览

#### Scenario: 未知块类型
- **WHEN** 一轮结果包含未来未知块类型或单块必要字段无效
- **THEN** 页面显示可理解的“不支持此结果块”占位并继续展示其余有效块，不根据原始对象猜测内容

### Requirement: 对象列表、Entry、Evidence 与候选语义分离
原生 App MUST 区分项目列表、目录列表、知识列表、Entry 正文、Evidence 原文片段和 AI 候选稿。只有服务端提供明确 Entry 标识的对象才能读取当前知识正文；Evidence 块只能按服务端公开字段表达本轮已核验材料，不得把 Entry 来源信息冒充为本轮 Evidence，也不得把检索命中表达为已读取或已核验。

#### Scenario: 项目或目录列表
- **WHEN** list 块语义为项目或目录且列表项没有明确 Entry 对象
- **THEN** 页面展示不可展开的对象列表，不尝试调用 Entry 接口

#### Scenario: Evidence 块
- **WHEN** 结果包含 Evidence 块
- **THEN** 页面以“本轮核验依据”语义展示服务端结构化内容，不从文本解析 Entry ID、Source 标题或 quote，也不生成旧引用条

#### Scenario: Entry 详情的来源信息
- **WHEN** 用户展开当前 Entry 且只读接口返回该知识的来源摘要
- **THEN** 页面标注为“当前知识的来源信息”，不宣称该来源已被本轮 Agent 核验

#### Scenario: Candidate 块
- **WHEN** 结果包含 candidate 块
- **THEN** 页面显示“修改建议/候选稿，未应用”，不提供保存、创建 Candidate、更新正式知识或撤销按钮

### Requirement: 回答依据只使用明确元数据
原生 App MUST 只按正式块本身表达 Entry、Evidence、Candidate 和不足语义；没有明确依据元数据时 MUST NOT 默认显示“基于正式知识”、推断整段回答为纯知识库回答或从自然语言恢复旧 citation。客户端查看当前 Entry 正文 MUST NOT 自动发送消息、调用模型或改变 Agent 上下文。

#### Scenario: 只有文本回答
- **WHEN** completed 回答只有 text 块且没有 Evidence 元数据
- **THEN** 页面显示 AI 即时回答，不显示“基于正式知识”或伪来源入口

#### Scenario: 点击展开当前正文
- **WHEN** 用户点击知识列表中的 Entry 项
- **THEN** 客户端打开底部只读详情并只调用已有 Entry 只读接口，不发送聊天消息、不调用模型、不推进工作集

### Requirement: 回答文本使用安全的原生 Markdown 并可选择复制
原生 App MUST 仅在移动展示层使用原生组件解析适用的 text、candidate、Entry 正文、Evidence 文本和扁平历史回退，不修改服务端文本、存储、提示词或 Web。渲染 MUST 支持段落、移动端适度标题、强调、列表、引用、代码与链接；MUST 禁止原始 HTML 执行和图片加载，并限制链接为安全协议。长链接、代码和表格 MUST 不撑破屏宽，表格 MAY 使用横向滚动阅读回退。结构化块的外层语义、顺序、状态和去重规则 MUST 保持不变。

#### Scenario: Markdown 与普通文本
- **WHEN** 文本包含 Markdown 或普通纯文本
- **THEN** 客户端按原文渲染已有格式，普通文本内容不被补写或重排，未换行的自然语言编号不被擅自转成列表

#### Scenario: 不安全内容
- **WHEN** 文本包含原始 HTML、图片或非 `https/http/mailto` 链接
- **THEN** 客户端不执行 HTML、不加载图片、不打开不安全协议，且其余文本仍可阅读

#### Scenario: 选择复制
- **WHEN** 用户长按回答、候选、Evidence、Entry 块或当前知识正文
- **THEN** 原生文本可选择并复制完整内容，不出现 blocks 与扁平全文重复，也不影响列表点击、滚动或关闭

## REMOVED Requirements

### Requirement: 调查摘要有限且可解释
**Reason**: 正式移动端只消费统一 dialogue 状态和块，不再维护旧 investigate 摘要、轮次、停止原因的专用渲染合同。

**Migration**: 服务端明确交付的阶段、partial、insufficient 与其他块按新正式合同展示；共享调查能力不删除。


#### Scenario: 控制器完成调查
- **WHEN** 调查以 `controller_complete` 停止
- **THEN** 回答卡显示实际轮次/查询数和已完成深度查找，不展示仍在搜索

#### Scenario: 达到预算
- **WHEN** 调查以 max_rounds/query_budget/entry_budget/evidence_budget 停止
- **THEN** 页面明确说明在预算边界停止并列出未解决缺口，不写「已查完所有知识」

#### Scenario: 无进展或不足
- **WHEN** stop_reason 为 no_progress 或 insufficient
- **THEN** 页面显示没有发现更多可核验证据或当前知识不足，并保留已有引用
### Requirement: 引用 Sheet 区分回答、Entry 与 Source 原文
**Reason**: 旧 citation 来源条与详情由已空置的兼容字段驱动，容易把知识命中、Entry 当前内容和 Evidence 混为一体。

**Migration**: Evidence 块按真实语义原位展示；明确 Entry 可按需读取当前正文，不重建旧 citation。


#### Scenario: 打开项目范围引用
- **WHEN** 用户点击项目范围回答的一条 citation
- **THEN** Bottom Sheet 显示 Entry、目录、Source 与核验原文，并可关闭返回原滚动位置

#### Scenario: 打开 Workspace 范围引用
- **WHEN** 用户点击全部知识范围回答的一条 citation
- **THEN** Sheet 额外明确显示该 Evidence 的项目归属，避免误认为来自当前其他项目

#### Scenario: 历史对象后来变化或删除
- **WHEN** Citation 所指 Entry/Source 当前已变化或删除
- **THEN** Sheet 仍显示 Run 保存的标题/归属/quote 快照；当前对象入口不可用时明确说明，不改写历史回答

#### Scenario: 查看当前 Entry
- **WHEN** 用户从 citation Sheet 打开当前知识且 Entry 仍可访问
- **THEN** 当前 Entry 内容与「本次回答证据快照」分区标注，不能混为同一时点内容
### Requirement: 冲突双方证据可分别核验
**Reason**: 旧 `answer.conflicts` 不再是正式 dialogue 交付合同。

**Migration**: 服务端交付的 text、Evidence 或 insufficient 内容按块展示；不从旧扁平字段恢复专用冲突 UI。


#### Scenario: 双方证据有效
- **WHEN** answer.conflicts 包含两个当前 Run citation
- **THEN** 冲突卡并列显示双方观点和独立来源入口，两个入口分别打开对应原文

#### Scenario: 只有疑似冲突或缺口
- **WHEN** 调查摘要提到 conflict 但最终 answer 没有双边可引用 Evidence
- **THEN** 页面将其显示为待核验线索或缺口，不包装成已证实冲突卡
### Requirement: 回答后续动作使用结构化协议
**Reason**: 原生端不再提供固定“整理成知识”或持久 Candidate Draft 写操作。

**Migration**: dialogue candidate 块只作未应用建议展示；共享 Candidate 服务保留给其他调用方。


#### Scenario: completed 回答提供结构化动作
- **WHEN** 服务端返回 completed 回答、source Run、有效 citations，并明确该 Run 未采用用户陈述、模型通用知识或外部材料
- **THEN** 客户端可以 source_run_id 发起旧 `draft_candidate`，不从正文反推引用、basis 或项目

#### Scenario: partial 回答提供受限动作
- **WHEN** 服务端判定 partial 回答仍有完全由有效 Grove Evidence 支撑的可整理部分
- **THEN** 动作说明只整理有依据部分，未解决 gaps 不进入 Candidate 草稿事实

#### Scenario: 模型优先或混合回答不显示旧入口
- **WHEN** answer basis 包含用户陈述、模型通用知识或当前不可用外部材料
- **THEN** 页面不显示固定“整理成知识”，即使回答同时包含一个或多个 Grove Citation

#### Scenario: 历史回答恢复动作
- **WHEN** 用户重新打开本 change 上线前生成且按旧规则可用的历史回答
- **THEN** 动作仍锚定该历史 source Run 的范围快照；服务端按旧 Evidence 规则判断资格，Evidence 失效时显示可恢复错误而非改用当前回答
### Requirement: 回答、草稿与 Candidate 回执语义分离
**Reason**: 原生端不再创建或恢复持久 Candidate Draft/Candidate 回执。

**Migration**: AI 即时回答与 dialogue candidate 块仍使用不同文案，旧测试数据不迁移。


#### Scenario: 草稿生成完成
- **WHEN** operation Run 返回 draft 状态
- **THEN** 草稿卡使用 AI 建议语义并提供编辑/确认动作，不使用 confirmed 语义

#### Scenario: Candidate 创建完成
- **WHEN** Draft 确认并关联 pending Candidate
- **THEN** 回执显示待确认状态、来源与目标项目，不显示“正式知识已保存”
### Requirement: 回答正文的要点卡渲染
**Reason**: 旧 `answer.points` 被正式 `dialogue_blocks` 取代，保留专用渲染会形成双轨。

**Migration**: 历史回答仅保留简单扁平文本回退，新回答按 blocks 原序展示。


#### Scenario: 新回答带结构化要点
- **WHEN** 回答包含 `points` 且至少一条有效要点
- **THEN** 页面按分组标题、连续编号展示每条要点正文，不在要点内展示来源入口

#### Scenario: 历史回答无要点
- **WHEN** 回答不包含 `points`（历史数据或旧模型输出）
- **THEN** 页面保留现有纯文本正文与底部来源条，不显示空要点区

#### Scenario: 分组标题与编号可读
- **WHEN** 要点存在 `section` 分组
- **THEN** 分组标题以更醒目的样式展示，连续编号读屏可朗读
### Requirement: 底部来源条可核验可访问
**Reason**: 旧末尾 citations 条会重复排列知识并错误承接正式 Agent 的依据语义。

**Migration**: Evidence 块原位显示；Entry 当前正文从明确 Entry 对象按需读取。


#### Scenario: 点击底部来源 chip
- **WHEN** 用户点击回答卡底部的某个来源 chip
- **THEN** 打开证据原文 Sheet，展示该引用的 Entry 与 Source 原文，来源关系由应用层校验

#### Scenario: 触控与读屏
- **WHEN** 用户使用读屏或小尺寸触控
- **THEN** 来源 chip 提供 `查看引用：{Entry 标题}` 语义且最小触控高度为 44

#### Scenario: 语义不混淆
- **WHEN** 回答、草稿与待确认 Candidate 同屏出现
- **THEN** 要点卡保持「基于正式知识」的即时回答语义，不出现「已归档」或「正式知识」文案
### Requirement: 回答引用详情提供 Entry 定向后续操作
**Reason**: 原生端本轮移除 Entry Revision 写操作。

**Migration**: Entry 详情保持只读；共享 Revision 服务不删除。


#### Scenario: 当前有效引用显示修订动作
- **WHEN** completed/partial 回答的 citation 对应当前可写 Entry
- **THEN** 引用详情在 Entry/Source 原文之后提供目标明确的修订入口

#### Scenario: 只查看来源原文
- **WHEN** 用户打开 citation 但不发起修订
- **THEN** 页面只展示 Entry 与 Source Evidence，不创建 Draft、Run 或任何写对象
### Requirement: 回答、Candidate Draft 与 Entry Revision 语义不混淆
**Reason**: 两类持久写操作均从原生端移除，不再需要并列操作语义。

**Migration**: dialogue candidate 块继续明确“未应用”，不映射为持久 Draft。


#### Scenario: 同一回答提供两类后续动作
- **WHEN** 回答既可整理为 Candidate 且某条 citation 可修订
- **THEN** 页面分别说明“创建待确认知识”和“修改现有正式知识”，用户能看懂目标及确认后果

#### Scenario: Entry Revision 尚未确认
- **WHEN** 修订草稿已生成但未应用
- **THEN** 回答与 Entry 仍保持正式原内容，草稿标识为 AI 建议且不显示已更新
### Requirement: 回答下展示服务端确认的紧凑依据概览
**Reason**: 正式 adapter 不交付旧 `answer_basis`，继续展示会产生伪依据或兼容分支。

**Migration**: 只展示服务端正式 Entry/Evidence 等块的局部语义；无元数据时不推断全局依据。

#### Scenario: 模型优先回答依据
- **WHEN** completed 回答没有 Citation 且 basis 标记使用模型通用知识
- **THEN** 回答下显示“AI 通用知识 · 未使用你的知识库 · 未检索实时外部资料”，不显示伪来源入口

#### Scenario: 混合回答依据
- **WHEN** basis 包含两个 Grove Citation、两条用户陈述和模型通用知识
- **THEN** 紧凑概览分别显示三类实际依据，Grove 项仍可打开 Citation 原文，用户陈述项可查看对应消息摘要

#### Scenario: 需要外部材料
- **WHEN** basis 的 external material 状态为 required_unavailable
- **THEN** 回答附近明确显示当前未检索实时外部材料和因此未覆盖的边界，不暗示已经联网

#### Scenario: 历史回答没有 basis
- **WHEN** 旧 Run 不包含 `answer_basis`
- **THEN** 页面保持旧回答正文、状态、来源条与 Citation Sheet，不猜测或补造 AI 通用知识、用户陈述或外部材料标签

#### Scenario: 依据详情长内容
- **WHEN** 用户陈述摘要、Citation 或外部边界超过可用高度
- **THEN** 依据详情在 Sheet 内独立滚动、始终可关闭，并在关闭后恢复对话阅读位置
