## MODIFIED Requirements

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
