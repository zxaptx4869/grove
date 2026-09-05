# knowledge-agent-shared-execution-graph Specification

## Purpose
TBD - created by archiving change optimize-knowledge-agent-shared-execution-graph. Update Purpose after archive.
## Requirements
### Requirement: 服务端将复合计划编译为受限共享执行图
系统 MUST 在共享执行图能力开启且 quick 复合计划已规范化并固化后，由服务端把原始检索与结构化请求编译为版本化的数据集、Entry 内容、Evidence 和输出节点；节点类型、依赖、消费者和执行参数 MUST 来自闭合应用协议。模型与客户端 MUST NOT 提交 node id、fingerprint、依赖、范围、预算、并行度或任意执行表达式，图 MUST 在任何节点执行前持久化并绑定当前 Run、首次复合计划和冻结预算。

#### Scenario: 混合回答编译为领域节点
- **WHEN** 一份 quick 复合计划同时包含 Grove 语义检索、Entry Evidence、同集合 count、分组和最近对象输出
- **THEN** 服务端编译出受限 entry-set、内容/Evidence 与输出节点，并保存原始 request/requirement 到节点消费者的映射，不调用第二个规划模型

#### Scenario: 模型尝试提供图控制字段
- **WHEN** 复合计划候选或客户端请求包含依赖、node id、fingerprint、并发度、Workspace/项目 id 或未知节点类型
- **THEN** 这些字段不能进入可执行图；若它们使原复合计划 schema 非法，系统按既有规则拒绝整份计划并显式降级

#### Scenario: Worker 恢复已固化图
- **WHEN** 同一 Run 已保存与首次复合计划匹配的合法共享图后被重新领取
- **THEN** 系统复用该图及其中冻结预算，不因当前配置、模型输出或进程重启重新编译或改变节点语义

### Requirement: 等价数据集与输出节点只执行一次
系统 MUST 使用服务端 canonical key 和稳定 fingerprint 合并同一 Run 内完全等价的数据集与输出节点；等价判断 MUST 至少绑定节点/工具版本、规范化参数、上游节点、范围指纹、完整性合同和冻结预算，不得把 requirement id 或原始 request id 作为阻止共享的业务参数。系统 MUST NOT 使用向量相似、模型判断或模糊文本规则合并无法证明等价的查询。

#### Scenario: 两份请求使用相同结构化集合
- **WHEN** 多个回答义务分别请求同一类型与时间范围上的 count、group_count 和最近 Entry
- **THEN** 图只保留一个规范化 structured entry-set，输出节点共享该集合，底层集合准备不因消费者数量重复执行

#### Scenario: 重复语义检索服务多个义务
- **WHEN** 两份 retrieval request 具有相同规范化查询、范围、候选预算与完整性合同
- **THEN** 系统只执行一次 semantic entry-set 与必要读取，并把同一合法结果映射给全部消费者，不伪造多次工具成功记录

#### Scenario: 相似但不等价的查询
- **WHEN** 两份语义查询文字相近但过滤条件、预算、排序、范围或完整性合同不同
- **THEN** 服务端保留独立节点，不为减少调用而猜测它们等价

### Requirement: 图结构与总预算在执行前严格校验
系统 MUST 在执行前校验节点标识与 fingerprint 唯一、依赖存在且方向合法、图无环、节点有消费者、request/requirement 引用有效，并限制节点数、图深度、单节点依赖数、可执行工具调用、Entry、Evidence、桶、并发度、总耗时和 JSON 字节。可信范围 MUST 只由 Run 固化 owner、Workspace 和可选项目注入；图优化 MUST NOT 放大原复合计划或现有工具的预算。

#### Scenario: 编译器产生循环依赖
- **WHEN** 候选图存在自依赖、循环、未知上游或超过深度上限
- **THEN** 服务端在任何节点调用前拒绝该图、记录 server fallback，并在没有已提交图节点结果时使用现有串行执行路径

#### Scenario: 合并后的消费者超过原计划范围
- **WHEN** 某节点消费者引用原规范化计划以外的 request 或 requirement
- **THEN** 服务端拒绝图且不执行该节点，不从相邻义务或其他 Run 借用结果

#### Scenario: 图节点达到总预算
- **WHEN** 编译节点、依赖、工具调用或序列化大小超过服务端固化上限
- **THEN** 服务端不静默删除核心节点或扩大上限，而是显式记录图编译降级并保持原计划的兼容执行语义

### Requirement: 调度器确定性执行依赖并只安全并行
系统 MUST 按确定性拓扑顺序执行共享图；只有依赖均已达到可消费终态且进入服务端并行白名单的独立只读节点才能并行。并行节点 MUST 使用独立数据库会话和从 Run 固化的不可变工具上下文，MUST NOT 共享 `AsyncSession`、可变预算或工具上下文；Evidence、Run、审计、检查点和最终结果写入 MUST 由协调器重新校验后串行提交。

#### Scenario: 两个独立只读输出可并行
- **WHEN** 两个 ready 节点互不依赖、使用不同只读结果且均在并行白名单与预分配预算内
- **THEN** 调度器可以在配置并发上限内同时执行，但按稳定 node id 校验、记录和持久化结果

#### Scenario: Evidence 节点与共享写状态
- **WHEN** ready 集合包含需要创建当前 Run Evidence、更新检查点或分配工具审计序号的节点
- **THEN** 这些共享写步骤由协调器串行执行，不与其他任务共享数据库会话或依赖完成顺序获得正确性

#### Scenario: 上游失败阻止后继
- **WHEN** 一个数据集节点失败或结果不满足后继节点的输入合同
- **THEN** 调度器不执行受阻后继，将其标记为受上游影响的 failed/partial，同时继续执行其他独立分支

### Requirement: 节点检查点可恢复且终态不可自动重试
系统 MUST 为每个节点保存与图版本、fingerprint、上游结果和冻结预算绑定的有界终态检查点。`completed`、`empty`、`limited`、`partial` 与 `failed` 均表示一次已提交的节点结果，Worker 恢复 MUST 复用这些终态并只重放没有已提交结果的节点；进程内 running 或返回后尚未提交的结果不得视为完成。取消后迟到结果 MUST 被丢弃。

#### Scenario: 一个共享节点完成后进程退出
- **WHEN** semantic entry-set 已提交终态而依赖它的 Evidence 节点尚未执行时 Worker 租约超时
- **THEN** 恢复复用同一 semantic 结果，只执行未完成后继，不再次召回或改变已完成结果

#### Scenario: partial 节点后发生恢复
- **WHEN** 节点已保存合法部分结果和 `partial` 状态后 Worker 退出
- **THEN** 恢复保留该结果与缺口，不因恢复获得新预算或自动重试该节点

#### Scenario: 执行期间取消
- **WHEN** 用户在并行节点运行期间请求取消
- **THEN** 调度器停止启动新节点，协调器拒绝提交取消后返回的迟到结果，Run 进入 cancelled 且不生成正常回答

#### Scenario: 已持久化快照损坏
- **WHEN** 恢复发现 graph/state 超过字节上限、schema 非法或 plan/node fingerprint 不匹配
- **THEN** Run 显式失败并记录原因，不重新编译、切换串行执行或猜测历史节点结果

### Requirement: 共享图物化兼容结果并完整记录实际执行
系统 MUST 将合法图节点结果确定性物化为现有复合执行输入、工具事实、Evidence 和缺口，使最终综合、逐项覆盖、Citation、answer basis 与公开 API 继续使用既有协议。每次实际模型和工具调用 MUST 记录真实 provider、model、status、fallback、error、duration、usage、节点 fingerprint 与复用信息；共享一个节点不得伪造多次调用，被并行或复用的失败不得从 fallback 摘要消失。

#### Scenario: 多个义务共享一个 count 结果
- **WHEN** 一个完成的 aggregate node 服务多个回答义务
- **THEN** 服务端只生成一个稳定 result handle 和一次实际工具调用记录，并按合法消费者关系将结果用于逐项覆盖

#### Scenario: 图编译失败后兼容串行成功
- **WHEN** 图尚未执行即编译或首次持久化失败，而现有串行执行器成功完成回答
- **THEN** 用户继续收到兼容 answer，但 fallback 摘要明确记录共享图降级，不把该 Run 标记为完全正常图执行

#### Scenario: 部分节点执行后调度失败
- **WHEN** 图已有节点终态提交后另一个节点或调度阶段失败
- **THEN** 系统保留合法节点并形成诚实 partial/failed 与缺口，不整体回退串行执行导致重复调用

#### Scenario: 图执行没有知识写入副作用
- **WHEN** 共享图完成、部分完成、恢复或取消
- **THEN** 系统只写入 Conversation、Message、Run、当前 Run Evidence、模型/工具审计与回答快照，不创建或修改 Entry、Source、Candidate、Draft、目录、Operation 或事实工作集

### Requirement: 补查只扩展严格新增的共享只读节点
当 quick 首次执行已固化共享图时，系统 MUST 保留首次 graph/state 不变，并将经服务端规范化的补查请求编译为独立版本化补查图。编译器 MUST 先以工具版本、规范化参数、完整性合同和 Run 范围识别首次已完成的等价请求，只为剩余新请求生成有冻结补查预算的节点；任一首次终态节点、result handle 或 Evidence MUST NOT 重放。

#### Scenario: 补查请求完全重复首次节点
- **WHEN** 补查候选只包含与首次某检索或结构化输出完全等价的请求
- **THEN** 编译器不生成新节点，补查以 `no_novel_request` 停止并保留原结果

#### Scenario: 补查图部分复用与部分新增
- **WHEN** 一份补查候选同时包含一个已完成等价请求和一个新检索请求
- **THEN** 服务端拒绝该混合候选而不静默替模型删除重复项，保留首次已提交结果并且不编译任何新节点

#### Scenario: 补查图节点恢复
- **WHEN** 补查图已固化并提交一个终态节点后 Worker 中断
- **THEN** 恢复使用同一补查 graph/state 和冻结预算，只执行 pending 节点，不改写首次图或重编译补查图

#### Scenario: 补查图已开始后失败
- **WHEN** 补查图已有节点终态提交，后续调度或节点失败
- **THEN** 系统保留首次结果和补查已提交结果，不整体切换串行重放，并以真实 partial/fallback 收尾
