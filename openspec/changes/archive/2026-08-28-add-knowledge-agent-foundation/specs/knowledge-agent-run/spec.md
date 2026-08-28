## ADDED Requirements

### Requirement: 持久化异步 Run
系统 MUST 为每条被接受的用户问题创建持久化只读 Agent Run，并立即返回 Run 标识；Run MUST 固化用户消息、助手消息、Workspace/项目范围和创建时间，客户端 MUST 能通过查询恢复执行状态。

#### Scenario: 问题进入等待状态
- **WHEN** 空闲对话接受一条新用户问题
- **THEN** 系统创建状态为 `waiting` 的 Run 并返回而无需等待 AI 完成

#### Scenario: 客户端恢复执行状态
- **WHEN** 客户端在提交后断线并重新查询 Run
- **THEN** 系统返回持久化的状态、当前步骤、范围快照、降级摘要和终态结果

### Requirement: 首次问答使用固定有限执行图
系统 MUST 按“搜索正式知识、读取候选 Entry、读取真实来源证据、组织回答、校验引用”的固定顺序执行首次问答；每个工具步骤 MUST 有服务端配置的次数与结果上限，模型 MUST NOT 自行创建无限工具循环。

#### Scenario: 正常完成首次问答
- **WHEN** Worker 领取一个待执行 Run 且各阶段成功
- **THEN** 系统按固定执行图完成步骤并将经校验的回答原子写入助手消息

#### Scenario: 历史消息不作为事实上下文
- **WHEN** 同一对话提交第二个问题且尚未实现连续追问能力
- **THEN** 系统独立检索当前问题，不把历史回答当作正式知识或自动复用其证据集合

#### Scenario: 工具达到预算上限
- **WHEN** 某工具已达到本 Run 的调用或结果上限
- **THEN** 系统停止该工具的后续扩张并基于已有证据继续或明确标记知识不足

### Requirement: Run 状态与单会话串行
系统 MUST 仅允许 Run 在 `waiting`、`processing`、`completed`、`partial`、`failed`、`cancelled` 状态间按合法路径转换；同一对话 MUST 最多存在一个 `waiting` 或 `processing` Run。

#### Scenario: 活动 Run 时提交新问题
- **WHEN** 对话已有 `waiting` 或 `processing` Run 且用户提交新的 `client_message_id`
- **THEN** 系统返回冲突响应且不创建第二个活动 Run

#### Scenario: 终态后提交新问题
- **WHEN** 对话最近 Run 已进入任一终态且用户提交新问题
- **THEN** 系统允许创建新的 `waiting` Run

#### Scenario: 非法状态转换
- **WHEN** 执行器尝试将终态 Run 重新改为 `processing`
- **THEN** 系统拒绝转换且保留原终态

### Requirement: Run 领取与崩溃恢复
Worker MUST 通过数据库原子操作领取待执行 Run，并记录领取时间与重试次数；超过租约阈值的 `processing` Run MUST 在重试上限内恢复，超过上限 MUST 进入可解释的失败终态。

#### Scenario: 两个 Worker 竞争领取
- **WHEN** 两个 Worker 同时尝试领取同一个 `waiting` Run
- **THEN** 只有一个 Worker 获得执行权且不会提交两份助手回答

#### Scenario: Worker 重启后恢复
- **WHEN** Worker 在只读执行中退出且 Run 超过处理租约
- **THEN** 系统在重试上限内将 Run 重新入队并从固定执行图重新执行

#### Scenario: 超过恢复上限
- **WHEN** 同一 Run 连续超过允许的恢复次数
- **THEN** 系统将 Run 标记为 `failed`、释放会话活动槽并记录恢复失败原因

### Requirement: Run 可取消
系统 MUST 允许对话所有者取消 `waiting` 或 `processing` Run；Worker MUST 在步骤边界检查取消请求，取消后的模型结果 MUST NOT 写成正常回答。

#### Scenario: 取消等待中的 Run
- **WHEN** 用户取消尚未领取的 `waiting` Run
- **THEN** 系统将其标记为 `cancelled`、释放活动槽且 Worker 不再执行

#### Scenario: 取消处理中的 Run
- **WHEN** 用户取消正在模型调用中的 Run
- **THEN** 系统记录取消请求，并在可中断点将 Run 标记为 `cancelled`且丢弃未提交的模型结果

#### Scenario: 取消其他用户的 Run
- **WHEN** 用户请求取消无权访问的 Run
- **THEN** 系统返回 404 且不改变该 Run

### Requirement: 终态提交保持一致
系统 MUST 在同一事务中提交助手消息结果、Run 终态和活动槽释放；失败、取消或重复执行 MUST NOT 留下被当作正常完成答案的半成品消息。

#### Scenario: 回答提交成功
- **WHEN** 回答和引用通过最终校验
- **THEN** 系统原子写入助手消息、Run 结果与 `completed` 或 `partial` 终态并释放活动槽

#### Scenario: 最终提交失败
- **WHEN** 数据库在提交助手回答时失败
- **THEN** 系统不暴露部分完成答案且 Run 可按恢复规则重试或失败

### Requirement: 分阶段 AI 可观测性
系统 MUST 为 embedding、重排、回答及每次工具调用保存阶段、provider、model、fallback 状态、错误和耗时，并在 Run 上汇总用户可识别的降级状态；系统 MUST NOT 把局部降级记录为完全正常。

#### Scenario: 全阶段正常
- **WHEN** embedding、重排和回答均由配置的真实模型成功完成
- **THEN** 各阶段记录实际 provider/model、`is_fallback=false` 且 Run 无降级摘要

#### Scenario: embedding 降级但回答成功
- **WHEN** embedding 失败后使用确定性召回且回答模型成功
- **THEN** embedding 阶段记录降级原因，回答阶段记录实际模型，Run 汇总为部分降级

#### Scenario: 回答模型不可用
- **WHEN** 检索已有结果但回答模型未配置或调用失败
- **THEN** 系统明确记录回答阶段失败并将 Run 标为 `partial` 或 `failed`，不得伪装为正常 AI 回答
