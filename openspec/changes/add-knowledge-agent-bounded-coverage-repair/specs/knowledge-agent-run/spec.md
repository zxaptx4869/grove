## ADDED Requirements

### Requirement: quick Run 持久化一次覆盖补查决策与检查点
启用覆盖补查的 quick 复合 Run MUST 在补查 planner 前保存版本化控制快照，至少包含首次合法 answer/coverage/answer basis/Run 状态候选、可修复 requirement id、固化执行模式、冻结预算、阶段、停止原因和错误摘要；规范化补查计划、串行执行快照或共享补查 graph/state MUST 在各自首次使用前持久化。旧 Run 缺少这些字段时 MUST 保持可读并不反向生成补查。

#### Scenario: 首次回答后进入补查
- **WHEN** quick Run 已生成首次合法回答与可修复 coverage，且补查开关对该新 Run 开启
- **THEN** Worker 先提交基线控制快照和冻结预算，再调用最多一次补查 planner

#### Scenario: 旧 Run 没有补查字段
- **WHEN** API、历史分页或 Worker 读取本 change 上线前完成的 Run
- **THEN** 系统返回原 answer、Citation、coverage、basis 和 fallback，补查内部字段保持空且不重新执行

#### Scenario: 幂等消息重试
- **WHEN** 客户端以同一 `client_message_id` 重试已进入补查的提交
- **THEN** 系统返回同一 Run 和同一补查状态，不创建新消息、新 Run 或第二次补查

#### Scenario: 补查期间取消
- **WHEN** 用户在补查规划、新节点或再综合期间取消 Run
- **THEN** Worker 在下一安全边界停止，不提交正常回答或推进工作集，并按既有 cancelled 终态释放会话活动槽

#### Scenario: 终态提交保持一致
- **WHEN** 补查成功、部分成功或失败保底后 Run 收尾
- **THEN** 系统在同一事务边界提交最终或基线 answer、coverage、answer basis、fallback、Run 终态、助手消息与活动槽释放，不留下伪 completed 半成品
