## ADDED Requirements

### Requirement: 候选草稿使用受控 operation Run
系统 MUST 为已接受的 draft_candidate 请求创建 `run_kind=draft_candidate` 的持久化 Run，固化 source_run_id、目标项目和 Draft；该 Run MUST 复用单会话活动槽、领取、取消、租约恢复、终态提交和可观测性，但 MUST NOT 执行问答上下文决策、回答模式路由、搜索、调查或工作集推进。

#### Scenario: 草稿 Run 进入等待
- **WHEN** 合法显式整理请求被接受
- **THEN** 系统创建 waiting operation Run、generating Draft 和助手占位并立即返回

#### Scenario: 草稿 Run 正常完成
- **WHEN** Worker 生成并校验 Candidate Draft
- **THEN** 系统原子提交 completed Run、draft 状态、助手说明并释放活动槽，且不更新工作集

#### Scenario: 草稿 Run 取消
- **WHEN** 用户取消 waiting 或 processing 的 draft_candidate Run
- **THEN** 系统按既有取消边界停止模型结果提交，把 Run 标为 cancelled、Draft 标为 cancelled，不创建 Source 或 Candidate

#### Scenario: 草稿 Run 恢复
- **WHEN** Worker 中断后 operation Run 超过租约且未超重试上限
- **THEN** 系统恢复同一 Run/Draft 并安全重放生成步骤，不创建重复 Draft 或 Candidate

#### Scenario: 操作阶段可观测
- **WHEN** 草稿生成模型或确认工具成功、降级或失败
- **THEN** 系统分别记录 purpose、provider、model、fallback/error、耗时和受影响阶段，不把失败标为正常
