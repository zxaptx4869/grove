# knowledge-agent-investigation Specification

## Purpose
TBD - created by archiving change add-knowledge-agent-bounded-investigation. Update Purpose after archive.
## Requirements
### Requirement: 回答模式可选择且可追溯
系统 MUST 接受 `auto`、`quick`、`investigate` 三种回答模式并同时持久化请求模式与实际模式；`quick` MUST 使用单轮问答，`investigate` MUST 使用有界调查，`auto` MUST 由独立结构化路由选择，路由失败 MUST 显式降级到 `quick` 而不得伪装成正常路由。

#### Scenario: 自动选择快速回答
- **WHEN** 用户以 `auto` 提交一个无需多轮补查的问题且路由成功
- **THEN** Run 保存请求模式 `auto`、实际模式 `quick` 并执行单轮问答

#### Scenario: 自动选择调查
- **WHEN** 用户以 `auto` 提交多方面、需补查或需核对冲突的问题且路由成功
- **THEN** Run 保存请求模式 `auto`、实际模式 `investigate` 并创建有界调查

#### Scenario: 自动路由失败
- **WHEN** 路由模型未配置、超时、调用失败或返回非法结构
- **THEN** 系统显式记录 fallback 原因、选择实际模式 `quick` 并继续受控单轮问答

#### Scenario: 用户强制调查
- **WHEN** 用户以 `investigate` 提交问题
- **THEN** 系统不调用模式路由而直接创建有界调查

### Requirement: 调查控制器只提出结构化下一步
系统 MUST 在每轮向调查控制器提供当前问题、可信范围摘要、工作集摘要、已执行查询、证据账本摘要与剩余预算；控制器 MUST 只能返回 `search`、`answer` 或 `insufficient` 动作、有限文本查询以及覆盖/缺口/冲突摘要，MUST NOT 控制工具名、对象标识、Workspace/项目或预算上限。

#### Scenario: 控制器提出补查
- **WHEN** 当前证据仍有明确缺口且存在剩余预算
- **THEN** 控制器可返回 `search` 和不超过服务端每轮上限的新文本查询，由应用校验后执行固定只读工具链

#### Scenario: 控制器认为证据足够
- **WHEN** 当前证据已覆盖问题且控制器返回 `answer`
- **THEN** 系统停止新增查询并进入最终综合

#### Scenario: 控制器判断无法回答
- **WHEN** 当前正式知识不足且控制器返回 `insufficient`
- **THEN** 系统停止调查并保留未解决缺口供最终不足说明使用

#### Scenario: 控制器越权输出
- **WHEN** 控制器输出范围标识、任意工具名、对象 UUID、预算修改或不符合 schema 的内容
- **THEN** 系统忽略越权字段、记录异常，并按安全停止或受控 fallback 处理

### Requirement: 调查受服务端硬预算约束
系统 MUST 为调查固化服务端轮次、每轮查询、总查询、不同 Entry 与 Evidence 预算；默认最多三轮，客户端与模型 MUST NOT 放大预算。应用 MUST 先汇总本轮合法查询的候选，再以稳定的全局选择决定进入 Entry/Evidence 读取的候选；任何搜索返回顺序 MUST NOT 令首条查询垄断全部 Evidence。选择前和每次接纳前 MUST 检查剩余 Entry/Evidence 预算、单 Query/Entry/来源限额及重复成本，任何单轮批量结果和恢复路径都 MUST NOT 使实际不同对象数超过快照上限；达到任一上限后 MUST 确定性停止而不得继续后台执行。

#### Scenario: 达到默认轮次上限
- **WHEN** 调查已完成三轮且控制器仍请求搜索
- **THEN** 系统以 `max_rounds` 停止并基于已有证据回答或明确知识不足

#### Scenario: 达到总查询预算
- **WHEN** 新查询将超过当前调查固化的总查询数上限
- **THEN** 系统不执行超额查询、以 `query_budget` 停止并保存未解决缺口

#### Scenario: 单轮结果超过剩余 Entry 预算
- **WHEN** 当前只剩 1 个 Entry 名额而搜索批次返回多个新的合法 Entry
- **THEN** 系统确定性只接纳 1 个进入读取与账本，实际不同 Entry 数不超过上限并以 `entry_budget` 停止

#### Scenario: 达到 Evidence 预算
- **WHEN** 已形成的当前 Run 可引用 Evidence 达到固化上限
- **THEN** 系统不继续读取超额 Evidence、以 `evidence_budget` 停止并进入最终综合

#### Scenario: 达到对象或证据预算
- **WHEN** 调查达到固化的不同 Entry 或 Evidence 上限
- **THEN** 系统不再读取超额对象，以对应的 `entry_budget` 或 `evidence_budget` 原因确定性停止

#### Scenario: 多查询公平竞争 Evidence
- **WHEN** 同一轮多个合法查询都产生可读取候选且第一条查询单独即可填满剩余预算
- **THEN** 系统先给每个有候选的查询分配受限保留名额，再以稳定轮转选择剩余名额，第一条查询不得因返回顺序独占预算

#### Scenario: 重复候选不重复消耗预算
- **WHEN** 多条查询得到同一 Entry、相同或等价 quote，或同一来源的重复候选
- **THEN** 系统合并或限额该重复成本、保留全部可追溯关联，并把预算留给不同的可接纳 Evidence

#### Scenario: 候选读取后不可接纳
- **WHEN** 已选择的 Source 因不可引用、同 Entry 重复来源或等价 quote 被拒绝，且仍有预算和稳定排序后的候选
- **THEN** 系统继续选择替补候选；只有实际写入当前 Run 账本的 Evidence 才消耗 Evidence、Query 和 Entry 的接纳配额

#### Scenario: 真实冲突保留双边证据
- **WHEN** 不同 Entry/Source 的相反主张均形成当前 Run 可核验证据候选
- **THEN** 系统不因普通重复去重删除任一方，并在单项限额内为双方保留可选名额

#### Scenario: 候选已不可能接纳
- **WHEN** 剩余预算、去重或单项限额已使某查询的所有候选无法形成新的 Entry 或 Evidence
- **THEN** 系统不再读取该查询的无效后续对象，并将原因写入审计后继续最终综合或停止

#### Scenario: 恢复后剩余预算
- **WHEN** Worker 从已完成轮次恢复且账本已消耗部分 Entry/Evidence 预算
- **THEN** 后续轮次按重建后的剩余数量接纳对象，累计计数仍不超过固化上限

#### Scenario: 客户端提交更大预算
- **WHEN** 客户端随请求传入轮次、查询或对象上限
- **THEN** 系统忽略或拒绝这些字段并只使用服务端可信预算

### Requirement: 无进展与重复查询确定性停止
系统 MUST 对本调查内查询进行规范化去重；控制器没有提供合法新查询，或一个已完成轮次没有新增可用 Entry 与 Evidence 时，系统 MUST 以 `no_progress` 停止，MUST NOT 通过改写空格或大小写重复消耗预算。

#### Scenario: 控制器只返回重复查询
- **WHEN** 新一轮计划中的所有查询与本调查已执行查询规范化后相同
- **THEN** 系统不执行查询并以 `no_progress` 停止

#### Scenario: 一轮没有新结果
- **WHEN** 一轮所有查询完成后没有新增可用 Entry 或 Evidence
- **THEN** 系统提交该轮观察并以 `no_progress` 停止后续轮次

#### Scenario: 部分查询重复
- **WHEN** 控制器返回的查询中既有重复项也有合法新项
- **THEN** 系统只执行去重后的新查询并把实际执行数量计入预算

### Requirement: 调查轮次可恢复且可取消
系统 MUST 将每个已完成调查轮次作为恢复检查点；租约恢复 MUST 复用已提交轮次和账本并从下一未完成步骤继续。Worker MUST 在路由、每次控制器调用、查询工具批次和最终综合边界使用可见最新事务状态的短会话检查取消。

#### Scenario: 完成两轮后 Worker 退出
- **WHEN** 调查前两轮已提交且 Worker 在第三轮前超过租约
- **THEN** 恢复执行重建前两轮账本并从第三轮未完成步骤继续，不重复提交前两轮

#### Scenario: 未完成轮次被重试
- **WHEN** Worker 在一轮结果事务提交前退出
- **THEN** 系统安全重置或幂等重放该轮且不产生重复查询记录或 Evidence

#### Scenario: 查询批次期间取消
- **WHEN** 用户在一个调查查询工具批次执行期间提交取消
- **THEN** Worker 在下一边界看到取消、丢弃未提交结果并不进入下一轮或最终正常回答

#### Scenario: 已完成轮次在取消后保留
- **WHEN** 调查完成若干轮后被取消
- **THEN** 已提交轮次保留用于审计，Run 与 Investigation 进入取消状态且不推进工作集

### Requirement: 调查停止结果对用户可解释
系统 MUST 在 Run 结果返回请求/实际模式、完成轮数、实际查询数、稳定停止原因、覆盖摘要、未解决缺口和冲突提示；达到预算或仍有未解决缺口时 MUST 明确标记，不得把受限调查描述为穷尽全部知识。

#### Scenario: 调查充分完成
- **WHEN** 控制器以 `answer` 停止且最终引用校验通过
- **THEN** 响应返回 `controller_complete`、实际轮次/查询数和覆盖摘要

#### Scenario: 达到预算但有部分证据
- **WHEN** 调查因预算停止且已有证据支持部分结论
- **THEN** 响应返回已有带引用结论、停止原因与未解决缺口，并按引用和覆盖结果确定 `partial` 或正常状态

#### Scenario: 调查后仍无证据
- **WHEN** 调查停止时没有足以支持事实结论的当前 Run Evidence
- **THEN** 响应明确标记 `insufficient`，不使用模型自身知识补齐

