## ADDED Requirements

### Requirement: entries Run 固化结构化查询计划与版本
系统 MUST 为启用结构化查询能力的 `actual_result_mode=entries` Run 持久化服务端校验后的计划、schema 版本、prompt 版本和计划模型可观测信息；计划字段对旧 Run保持可空。计划一经固化 MUST 在同一 Run 的重试、恢复和历史读取中保持不变，模型原始输出或非法参数不得作为可执行计划保存。

#### Scenario: 计划验证后持久化
- **WHEN** structured query planner 返回合法计划且服务端规范化成功
- **THEN** Run 在任何查询工具执行前保存规范化计划、版本和模型调用审计

#### Scenario: 历史 Run 没有查询计划
- **WHEN** 客户端读取本 change 上线前的 entries Run
- **THEN** API 继续返回旧 Entry 结果快照，查询计划字段为空且系统不猜测历史筛选或聚合

### Requirement: 结构化查询 Run 可取消和崩溃恢复
Worker MUST 在查询规划前后、每个确定性工具调用前后和最终提交前检查取消；恢复时 MUST 复用已固化计划和同 Run 中已提交的幂等工具结果，只重放未完成的只读步骤。取消、超出恢复上限或迟到工具结果 MUST NOT 形成正常 Entry 结果快照。

#### Scenario: 计划后 Worker 崩溃
- **WHEN** Worker 已提交规范化计划但尚未完成全部工具调用时退出
- **THEN** 恢复复用同一计划，按调用指纹复用已提交结果并继续未完成步骤，不再次调用规划模型

#### Scenario: 聚合执行期间取消
- **WHEN** 用户在 aggregate_entries 执行期间请求取消 Run
- **THEN** Worker 在下一个边界丢弃未提交的迟到结果，将 Run 标为 cancelled 并释放活动槽

#### Scenario: 重放只读查询
- **WHEN** 未完成 query_entries 在租约恢复后重放
- **THEN** 重放不修改正式 Entry，并生成同一计划语义下的结果或明确对象已变化/执行异常

### Requirement: 结构化查询终态原子提交且可观测
系统 MUST 在同一事务中提交 v2 Entry 结果快照、助手兼容消息、Run 终态和活动槽释放；每次规划与工具调用 MUST 按实际 provider、model、fallback、状态、完整性、错误和耗时进入 Run 可观测汇总。部分失败 MUST 保留合法结构化结果并标记 partial/unknown，成功响应不得掩盖规划降级或工具异常。

#### Scenario: 组合查询正常完成
- **WHEN** count、group_count 与 entries 输出都正常执行并通过结果预算校验
- **THEN** 系统原子提交同一 v2 快照与 completed Run，调用顺序和每个输出完整性可查询

#### Scenario: 规划降级后旧查找成功
- **WHEN** 结构化查询规划失败但既有有限语义查找成功
- **THEN** Run 可以返回兼容 Entry 列表，但 fallback 汇总标识 structured_query_plan 失败，结果不包含伪聚合或精确全集承诺

#### Scenario: 一个工具部分失败
- **WHEN** 聚合完成但 Entry 列表装配出现部分不可用对象
- **THEN** 系统保留可确认的聚合和合法 Entry，按各输出完整性标记 Run/结果为 partial 或 unknown，不提交相互矛盾的半份快照
