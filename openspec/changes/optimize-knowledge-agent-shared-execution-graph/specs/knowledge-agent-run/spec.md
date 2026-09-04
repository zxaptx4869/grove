## ADDED Requirements

### Requirement: quick Run 可以固化共享执行图状态
启用共享执行图的 quick 复合 Run MUST 保存与首次规范化计划绑定的版本化图、冻结预算和节点终态；图执行状态 MUST 继续受同一 Conversation 活动槽、Worker 领取、租约恢复、重试上限、取消和终态原子提交控制。旧 Run、未启用共享图的 Run 和已有 `CompositeAnswerExecution v1` MUST 继续按原记录读取与执行，系统 MUST NOT 为历史 Run 反向生成共享图。

#### Scenario: 新 quick Run 进入共享执行
- **WHEN** 复合回答与共享执行图开关均开启，Run 已固化合法 `CompositeAnswerPlan v1`
- **THEN** Worker 在任何图节点前保存图与预算，并继续使用原 Run 活动槽和取消状态，不创建第二个子 Run

#### Scenario: 旧 Run 没有共享图字段
- **WHEN** API、Worker 或历史分页读取迁移前完成的 Run
- **THEN** 共享图字段保持空且原 answer、执行快照、coverage、basis 和状态照常可读，不推断或执行新图

#### Scenario: 租约恢复复用图节点
- **WHEN** processing Run 租约超时且合法图中已有终态节点
- **THEN** Worker 在恢复次数上限内重新领取同一 Run、复用终态节点并继续 pending 节点；超过上限仍按既有规则失败并释放活动槽

#### Scenario: 开关回滚不改写进行中图 Run
- **WHEN** 部署关闭共享图开关时仍存在已经持久化图的 processing/waiting Run
- **THEN** 这些 Run 继续按各自固化图恢复，新 Run 才使用串行路径，系统不得让进行中 Run 整体重跑旧执行器

### Requirement: 共享图预算和取消在节点边界生效
系统 MUST 为共享图固化节点数、深度、工具调用、对象、Evidence、桶、并发、字节和总耗时预算，并在节点启动、结果接纳、检查点与终态提交前检查取消和剩余预算。并行执行不得因竞态重复消费额度或使实际总量超过 Run 固化上限；达到预算时保留合法结果并明确标记受影响节点和回答义务。

#### Scenario: 并行 ready 节点竞争剩余额度
- **WHEN** 多个 ready 节点的潜在对象或 Evidence 总量超过剩余 Run 预算
- **THEN** 调度器按稳定顺序预分配有界额度，只执行获准部分，并把未获额度节点标记为 limited/partial 而不是由完成先后决定结果

#### Scenario: 节点返回时用户已经取消
- **WHEN** 独立会话中的只读节点完成，但协调器在接纳前发现 Run 已请求取消
- **THEN** 该结果不写入图 state、Evidence、工具成功记录或正常回答，Run 按 cancelled 收尾

#### Scenario: 图快照达到字节上限
- **WHEN** graph 或 state 无法在保留节点身份、依赖、状态、完整性和必要句柄的前提下写入配置的 TEXT 字节预算
- **THEN** 系统显式失败或在图尚未开始时降级串行，不静默截断关键恢复信息后继续

### Requirement: 共享图保持 Workspace 隔离和只读副作用边界
共享图的每个节点 MUST 从父 Run 重新构造并校验 owner、Workspace 和可选项目范围；节点结果、fingerprint、复用与依赖 MUST 限于同一 Run。并行会话、恢复、去重和兼容物化 MUST NOT 跨 Workspace、项目或 Run 读取、关联或复用 Entry/Evidence，也不得获得知识写入权限。

#### Scenario: 相同查询存在于两个 Workspace
- **WHEN** 两个 Workspace 的不同 Run 使用完全相同的规范化查询和输出参数
- **THEN** 它们拥有不同范围绑定与图结果，任何节点、Entry、Evidence、result handle 或缓存都不能跨 Run 共享

#### Scenario: 项目范围图节点被并行执行
- **WHEN** 一个项目范围 Run 同时执行多个独立节点
- **THEN** 每个独立数据库会话只读取该 Run 固化项目内正式 Entry，其他项目和 Workspace 的对象不进入候选、结果或审计摘要

#### Scenario: 图结果被最终综合采用
- **WHEN** 图节点产生 Entry、Evidence、统计或列表并完成回答
- **THEN** 只有当前 Run 重新核验的 Evidence 和实际结构化结果可以进入回答依据，查询命中本身不创建或修改正式知识、Candidate、Draft、Operation 或事实工作集
