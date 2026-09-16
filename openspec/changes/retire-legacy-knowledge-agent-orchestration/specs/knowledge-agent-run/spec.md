## MODIFIED Requirements

### Requirement: Run 领取与崩溃恢复
Worker MUST 通过数据库原子操作领取待执行 Run，并记录领取时间与重试次数。Candidate 与 Entry Revision operation Run MUST 在既有重试上限内保持幂等恢复；普通 answer Run MUST 仅恢复尚未进入编排的领取阶段，或通过现有安全状态检查的统一 dialogue-loop 阶段。旧执行步骤、未知步骤、损坏状态和超过上限的 Run MUST 进入可解释的失败终态，不得被送入统一循环。

#### Scenario: 两个 Worker 竞争领取
- **WHEN** 两个 Worker 同时尝试领取同一个 `waiting` Run
- **THEN** 只有一个 Worker 获得执行权且不会提交两份助手回答或重复 operation 结果

#### Scenario: 统一循环安全恢复
- **WHEN** answer Run 在领取后、进入循环前退出，或统一 dialogue-loop 留下允许恢复的持久化状态并超过租约
- **THEN** 系统在重试上限内重新入队同一 Run，并继续使用统一循环

#### Scenario: 旧执行快照停止恢复
- **WHEN** answer Run 在旧 context、basis、result-mode、investigation、composite、coverage 或 shared-graph 步骤超过租约
- **THEN** 系统将 Run 标为 `failed`、释放会话活动槽并记录旧快照不可安全恢复
- **AND** 系统不调用统一 dialogue-loop 接管该 Run

#### Scenario: operation Run 恢复
- **WHEN** Candidate 或 Entry Revision Run 超过处理租约且没有超过恢复上限
- **THEN** 系统继续按既有幂等规则重新入队同一 Run

#### Scenario: 超过恢复上限
- **WHEN** 同一 Run 连续超过允许的恢复次数
- **THEN** 系统将 Run 标记为 `failed`、释放会话活动槽并记录恢复失败原因

### Requirement: Run 可取消
系统 MUST 允许对话所有者取消 `waiting` 或 `processing` Run；Worker、统一 dialogue-loop 适配器、Candidate、Entry Revision 和只读搜索 MUST 通过能读取其他事务最新提交状态的短会话，在各自既有安全边界检查取消请求。取消后的模型或工具结果 MUST NOT 写成正常回答、正式知识或 operation 结果。

#### Scenario: 取消等待中的 Run
- **WHEN** 用户取消尚未领取的 `waiting` Run
- **THEN** 系统将其标记为 `cancelled`、释放活动槽且 Worker 不再执行

#### Scenario: 取消处理中的 answer Run
- **WHEN** 用户取消正在统一 dialogue-loop 中处理的 answer Run
- **THEN** 系统记录取消请求，并在下一个可中断点识别取消、丢弃未提交结果且不更新工作集

#### Scenario: 取消 operation Run
- **WHEN** 用户取消正在生成 Candidate 或 Entry Revision 的 Run
- **THEN** Worker 在既有安全边界识别共享取消信号并进入 `cancelled`，不提交正式 Entry 变更

#### Scenario: MySQL 长事务期间取消
- **WHEN** Worker 在 MySQL 执行长事务且另一请求提交取消
- **THEN** 后续步骤边界使用独立短会话看到最新取消状态并终止 Run

#### Scenario: 取消其他用户的 Run
- **WHEN** 用户请求取消无权访问的 Run
- **THEN** 系统返回 404 且不改变该 Run

## REMOVED Requirements

### Requirement: 知识问答使用 quick 或有界调查执行图
**Reason**: 普通 answer Run 已由统一 dialogue-loop 取代旧 quick/investigate 执行图。
**Migration**: 新 Run 只通过 `production_adapter` 进入统一循环；历史 Run 继续只读。

### Requirement: 结构化 Entry 查找使用独立有界执行图
**Reason**: 旧 runner 的 entries 分支与独立执行器退役，统一循环通过现行只读工具返回结构化结果。
**Migration**: 保留 API 的 `result_mode` 和历史结果快照字段，不恢复旧执行图。

### Requirement: Run 持久化请求策略与实际回答依据
**Reason**: 该需求混合了现行请求字段与已退役 composite/basis 执行快照；旧执行部分不再生成或恢复。
**Migration**: 保留请求字段、历史 basis/composite 投影和现行统一循环输出，不反向生成旧快照。

### Requirement: 依据规划与实际执行可观测
**Reason**: 旧 composite/basis planner 的阶段合同随执行器退役。
**Migration**: 使用统一 dialogue-loop 的模型、工具、fallback 与预算可观测记录；历史记录继续读取。

### Requirement: entries Run 固化结构化查询计划与版本
**Reason**: 旧 entries 执行分支不再为新 Run 生成独立 planner 快照。
**Migration**: 统一循环直接使用现行只读工具合同，历史 structured query 字段保持可空可读。

### Requirement: 结构化查询 Run 可取消和崩溃恢复
**Reason**: 旧 runner 的 structured-query 执行图不再恢复。
**Migration**: 当前统一循环和只读工具使用共享取消控制；旧快照明确失败收尾。

### Requirement: 结构化查询终态原子提交且可观测
**Reason**: 旧独立执行图的终态合同不再适用于新 answer Run。
**Migration**: 现行结构化结果由统一循环与 `production_adapter` 按当前合同提交。

### Requirement: quick Run 可以固化共享执行图状态
**Reason**: 共享执行图执行器退役。
**Migration**: 历史图字段继续只读，不生成、恢复或转换为统一循环状态。

### Requirement: 共享图预算和取消在节点边界生效
**Reason**: 共享执行图节点调度不再执行。
**Migration**: 新 Run 使用统一 dialogue-loop 的预算和取消边界。

### Requirement: 共享图保持 Workspace 隔离和只读副作用边界
**Reason**: 共享执行图节点调度不再执行。
**Migration**: 统一循环继续承担现行 Workspace、权限与只读工具边界。

### Requirement: quick Run 持久化一次覆盖补查决策与检查点
**Reason**: 旧 coverage-repair 执行器退役。
**Migration**: 历史补查字段继续可读，不生成、恢复或转换旧补查检查点。

