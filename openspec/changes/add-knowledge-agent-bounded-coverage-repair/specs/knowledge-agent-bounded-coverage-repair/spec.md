## ADDED Requirements

### Requirement: 只有真实且可修复的逐项缺口进入一次补查
系统 MUST 在 quick 复合回答首次固定计划、只读执行和合法综合完成后，从服务端派生的逐项 coverage 中筛选状态为 `insufficient` 或 `partial` 且能由现有 Grove 闭合只读工具改善的回答义务。每个 Run MUST 最多进入一次补查阶段；`answered`、`failed`、纯模型输出漏答和没有真实外部工具可满足的 `external_required` MUST NOT 触发工具补查。

#### Scenario: Grove 依据缺口可补查
- **WHEN** 首次 coverage 中一项 `grove_only` 义务为 `insufficient`，另一项 `grove_required` 义务因有限输入为 `partial`
- **THEN** 服务端可将这两项列为唯一补查候选目标，不把其他义务加入目标

#### Scenario: 已回答义务不重查
- **WHEN** 首次 coverage 同时包含 `answered`、`partial` 和 `insufficient`
- **THEN** 补查准入只考虑可修复的 `partial/insufficient`，已回答义务不被再规划或重新执行

#### Scenario: 当前无工具的外部缺口
- **WHEN** 义务依赖当前价格或政策且 coverage 为 `partial/insufficient`，当前 Run 没有真实外部搜索工具
- **THEN** 系统保留该缺口而不发起 Grove 工具补查，不声称已联网或已核验

#### Scenario: 补查不形成循环
- **WHEN** 补查执行和再综合后仍有 `partial/insufficient` 义务
- **THEN** 系统以剩余 gaps 和真实停止原因收尾，不调用第二份补查计划或任何通用 Agent loop

### Requirement: 补查计划是闭合模型候选并由服务端规范化
模型 MUST 只能针对服务端给定的可修复 requirement id 提出有界 retrieval 或结构化请求候选，MUST NOT 新增、删除、重排或改写首次回答义务与计划。服务端 MUST 在执行前校验 schema、目标义务、依据策略、请求数、字段与字节上限、闭合工具、重复请求和从 Run 注入的范围；只有服务端规范化的计划可被固化和执行。

#### Scenario: 候选改写首次义务
- **WHEN** 模型候选包含新回答义务、修改后的义务摘要或不在准入集合中的 requirement id
- **THEN** 服务端拒绝整份候选，保留首次计划和结果并记录显式 fallback

#### Scenario: 候选尝试提供范围或写工具
- **WHEN** 候选包含 owner、Workspace、项目、目录、Entry/Source id、SQL、外部搜索、写工具或未知字段
- **THEN** 服务端拒绝候选，不读取范围外对象也不产生任何写入副作用

#### Scenario: 候选重复已执行请求
- **WHEN** 候选与首次计划或同份候选中另一请求在工具版本、规范化参数、完整性合同和范围上完全等价
- **THEN** 服务端不对该请求产生新节点或新调用，整份非空候选若无任何新查询则以 `no_novel_request` 确定性停止

#### Scenario: 模型认为无有效补查
- **WHEN** 模型在闭合工具内无法提出会增加依据的新请求
- **THEN** 它可返回空补查候选，服务端固化 `no_novel_request` 并保留首次诚实缺口

### Requirement: 补查在任何工具前固化独立总预算
系统 MUST 在补查规划和节点执行前固化查询数、其中结构化请求数、新增节点数、工具调用、Entry、Evidence、分组桶、耗时、计划 JSON、图 JSON 和 state JSON 上限。补查最多两个新查询、其中最多一个结构化请求，默认最多八个新节点、六次工具调用、二十个 Entry、二十个 Evidence 和十五秒。已固化预算 MUST 在恢复或配置变化后保持不变，且 MUST NOT 放大首次执行或现有工具的单次上限。

#### Scenario: 补查请求或节点超限
- **WHEN** 规范化候选超过两个新查询、一个结构化请求或编译后超过冻结节点上限
- **THEN** 系统在任何补查工具调用前拒绝执行，不静默删除核心请求或扩大上限

#### Scenario: 执行中达到对象或耗时上限
- **WHEN** 新增节点在执行中消耗完冻结的工具、Entry、Evidence、桶或耗时额度
- **THEN** 调度器停止启动后续节点，保留已提交合法结果并将受影响义务标记为 `partial/insufficient`

#### Scenario: 部署后配置收紧
- **WHEN** 补查已固化预算后 Worker 中断，恢复时现行开关关闭或配置数值改变
- **THEN** 同 Run 继续使用已固化的次数和预算且不再调用 planner，新 Run 才使用新配置

### Requirement: 补查只执行新请求并复用已提交结果
系统 MUST 保留首次 `CompositeAnswerPlan`、execution、shared node state、result handle 和 Evidence，补查只对严格新增的规范化请求执行串行或共享图路径。首次与补查合法输入 MUST 以稳定句柄合并后再综合，已完成请求或节点 MUST NOT 因补查、恢复或终态失败而重放。

#### Scenario: 串行路径补查
- **WHEN** 首次复合计划使用串行执行器且补查候选包含一个新检索
- **THEN** 系统保留首次执行检查点，只执行新检索并将其合法 Evidence 合并进终态输入

#### Scenario: 共享图路径补查
- **WHEN** 首次执行已固化共享图节点终态，补查新请求与某已完成请求完全等价
- **THEN** 服务端在执行前识别无新节点并直接复用原 result/Evidence，不创建第二次工具成功记录

#### Scenario: 新查询部分命中已有 Evidence
- **WHEN** 新查询读取了首次已核验的同 Run Entry/Source
- **THEN** 系统复用已有 Evidence 行与句柄，不因新查询创建重复 Evidence

### Requirement: 补查失败保留首次合法回答并诚实收尾
系统 MUST 在发起补查 planner 前持久化可恢复的首次合法 answer、coverage、answer basis、Run 终态候选和 fallback 状态。补查计划、新节点、检查点或再综合失败 MUST NOT 删除或降低该首次合法结果；终态 MUST 保留其可用 points/Citation，并将补查失败、剩余缺口和真实 fallback 暴露给现有协议。

#### Scenario: 补查 planner 失败
- **WHEN** 首次回答已有合法 point 和 Citation，补查模型不可用或输出非法
- **THEN** Run 返回首次合法回答和 coverage，fallback 摘要标明补查规划失败，不伪装为完整回答

#### Scenario: 补查部分工具失败
- **WHEN** 补查的一个新节点成功而另一节点失败
- **THEN** 系统保留首次结果和新增合法结果，重算受影响义务为真实 `answered/partial/insufficient`，失败不从 fallback 汇总中消失

#### Scenario: 再综合模型失败
- **WHEN** 补查已产生新合法 Evidence 或 tool fact，但终态再综合模型失败
- **THEN** 系统以首次合法 answer 作为保底，可保留服务端确定性新事实但不声称模型已综合成功，Run 不得进入伪正常 completed

### Requirement: 补查支持取消、检查点、Worker 恢复和幂等重放
系统 MUST 在首次结果固化、补查规划前后、每个新请求/节点启动与接纳、检查点、再综合和终态提交前检查取消。补查计划、冻结预算、执行模式和所有已提交终态 MUST 在 Worker 恢复中复用；同一 `client_message_id` 或租约重试 MUST NOT 创建第二个补查阶段、重放已完成工具或重复提交回答。

#### Scenario: 规划后 Worker 中断
- **WHEN** 补查计划和冻结预算已提交，但第一个新节点尚未完成时 Worker 租约超时
- **THEN** 恢复复用同一计划和预算，从首个未提交节点继续，不再调用补查 planner

#### Scenario: 节点完成后 Worker 中断
- **WHEN** 一个补查节点已持久化为 `completed/empty/limited/partial/failed` 后 Worker 中断
- **THEN** 恢复将该终态视为已消耗的本次尝试，只执行尚未提交节点

#### Scenario: 节点返回时已取消
- **WHEN** 补查只读节点返回前用户已请求取消
- **THEN** 协调器不接纳迟到结果、Evidence 或伪工具成功记录，Run 按 cancelled 边界收尾

### Requirement: 补查保持 Run 范围隔离、可观测和无写入副作用
补查 planner 和每个只读节点 MUST 从父 Run 重建并校验 owner、Workspace、可选项目范围与对话上下文；计划、指纹、结果与 Evidence MUST 只在同 Run 内复用。每次实际规划、工具、模型与服务端停止 MUST 记录真实 purpose、provider、model、fallback/error、duration、usage、status、completeness 和复用信息。补查在成功、失败、恢复或取消中 MUST NOT 创建或修改 Entry、Source、Candidate、Draft、Extraction、目录、Operation 或事实工作集。

#### Scenario: 相同补查出现在两个 Workspace
- **WHEN** 两个不同 Workspace 的 Run 得到文字和参数完全相同的补查请求
- **THEN** 它们使用各自 Run 范围指纹与结果，节点、Entry、Evidence 和 result handle 不得跨 Run 共享

#### Scenario: 补查部分失败但 HTTP 成功
- **WHEN** Run 最终有可展示回答，但补查 planner 或某节点降级、超时或失败
- **THEN** fallback 摘要与逐项 coverage 仍可识别受影响阶段，成功响应不得掩盖降级

#### Scenario: 补查无写入副作用
- **WHEN** 补查完成、部分完成、失败、恢复或取消
- **THEN** 除 Conversation、Message、Run、当前 Run Evidence、模型/工具审计和回答快照外，正式知识与候选类对象计数均不变
