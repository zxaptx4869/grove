## MODIFIED Requirements

### Requirement: 调查受服务端硬预算约束
系统 MUST 为调查固化服务端轮次、每轮查询、总查询、不同 Entry 与 Evidence 预算；默认最多三轮，客户端与模型 MUST NOT 放大预算。应用在接纳每条搜索结果进入已发现集合、Entry 读取或 Evidence 读取前 MUST 检查剩余 Entry/Evidence 预算，任何单轮批量结果和恢复路径都 MUST NOT 使实际不同对象数超过快照上限；达到任一上限后 MUST 确定性停止而不得继续后台执行。

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

#### Scenario: 恢复后剩余预算
- **WHEN** Worker 从已完成轮次恢复且账本已消耗部分 Entry/Evidence 预算
- **THEN** 后续轮次按重建后的剩余数量接纳对象，累计计数仍不超过固化上限

#### Scenario: 客户端提交更大预算
- **WHEN** 客户端随请求传入轮次、查询或对象上限
- **THEN** 系统忽略或拒绝这些字段并只使用服务端可信预算

