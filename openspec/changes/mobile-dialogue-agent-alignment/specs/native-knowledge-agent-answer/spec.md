## MODIFIED Requirements

### Requirement: Run 过程只展示可验证阶段
原生 App MUST 以服务端 `dialogue_stage` 和 `dialogue_loop_status` 展示准备、检索知识、读取 Entry、核验证据、综合回答等用户可验证状态；`current_step` 只能用于旧响应回退。客户端 MUST NOT 展示隐藏推理、内部 continuation、控制器理由或与服务端无关的伪进度，且任一终态 MUST 停止进行中动效。

#### Scenario: 正式 Run 处理中
- **WHEN** `dialogue_loop_status` 为 waiting 或 processing 且存在已知 `dialogue_stage`
- **THEN** 过程卡显示该真实阶段、生成时范围和取消入口

#### Scenario: 步骤未知
- **WHEN** 客户端收到未识别的 future `dialogue_stage`
- **THEN** 使用稳定的“正在处理”通用文案且继续轮询，不崩溃或暴露原始枚举

#### Scenario: Run 终态
- **WHEN** `dialogue_loop_status` 进入 completed、partial、failed、cancelled、not_executed 或 unsupported
- **THEN** 过程卡转为对应持久终态，不继续显示“正在处理”或进行中动效

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

### Requirement: 长内容层可滚动且恢复对话
原生 App MUST 让 History、Scope 与上下文设置 Sheet 的长内容在 Sheet 内独立滚动，并让原位展开的长 Entry 正文跟随消息区滚动；关闭 Sheet 或收起正文后 MUST 保留对话阅读状态。长项目名、正文、错误或选项列表不得遮挡关闭、重试或 Composer。

#### Scenario: 长 Entry 正文
- **WHEN** 用户展开超过一屏的当前 Entry 正文
- **THEN** 正文随消息区滚动且可从同一列表项收起，不出现覆盖 Composer 的独立固定层

#### Scenario: 长历史或选项
- **WHEN** History、Scope 或上下文设置列表超过可用高度
- **THEN** 对应 Sheet 内可滚动，关闭后对话仍保留原消息位置和输入状态

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
- **THEN** 客户端只调用已有 Entry 只读接口并更新本地展开状态，不发送聊天消息、不调用模型、不推进工作集

## REMOVED Requirements

### Requirement: 调查摘要有限且可解释
**Reason**: 正式移动端只消费统一 dialogue 状态和块，不再维护旧 investigate 摘要、轮次、停止原因的专用渲染合同。

**Migration**: 服务端明确交付的阶段、partial、insufficient 与其他块按新正式合同展示；共享调查能力不删除。

### Requirement: 引用 Sheet 区分回答、Entry 与 Source 原文
**Reason**: 旧 citation 来源条与详情由已空置的兼容字段驱动，容易把知识命中、Entry 当前内容和 Evidence 混为一体。

**Migration**: Evidence 块按真实语义原位展示；明确 Entry 可按需读取当前正文，不重建旧 citation。

### Requirement: 冲突双方证据可分别核验
**Reason**: 旧 `answer.conflicts` 不再是正式 dialogue 交付合同。

**Migration**: 服务端交付的 text、Evidence 或 insufficient 内容按块展示；不从旧扁平字段恢复专用冲突 UI。

### Requirement: 回答后续动作使用结构化协议
**Reason**: 原生端不再提供固定“整理成知识”或持久 Candidate Draft 写操作。

**Migration**: dialogue candidate 块只作未应用建议展示；共享 Candidate 服务保留给其他调用方。

### Requirement: 回答、草稿与 Candidate 回执语义分离
**Reason**: 原生端不再创建或恢复持久 Candidate Draft/Candidate 回执。

**Migration**: AI 即时回答与 dialogue candidate 块仍使用不同文案，旧测试数据不迁移。

### Requirement: 回答正文的要点卡渲染
**Reason**: 旧 `answer.points` 被正式 `dialogue_blocks` 取代，保留专用渲染会形成双轨。

**Migration**: 历史回答仅保留简单扁平文本回退，新回答按 blocks 原序展示。

### Requirement: 底部来源条可核验可访问
**Reason**: 旧末尾 citations 条会重复排列知识并错误承接正式 Agent 的依据语义。

**Migration**: Evidence 块原位显示；Entry 当前正文从明确 Entry 对象按需读取。

### Requirement: 回答引用详情提供 Entry 定向后续操作
**Reason**: 原生端本轮移除 Entry Revision 写操作。

**Migration**: Entry 详情保持只读；共享 Revision 服务不删除。

### Requirement: 回答、Candidate Draft 与 Entry Revision 语义不混淆
**Reason**: 两类持久写操作均从原生端移除，不再需要并列操作语义。

**Migration**: dialogue candidate 块继续明确“未应用”，不映射为持久 Draft。

### Requirement: 回答下展示服务端确认的紧凑依据概览
**Reason**: 正式 adapter 不交付旧 `answer_basis`，继续展示会产生伪依据或兼容分支。

**Migration**: 只展示服务端正式 Entry/Evidence 等块的局部语义；无元数据时不推断全局依据。

