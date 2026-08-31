## ADDED Requirements

### Requirement: Entry Revision 使用独立受控 operation Run
Knowledge Agent Run MUST 支持 `run_kind=entry_revision`，固化 source_run_id 与 target_entry_id，并复用单会话活动槽、waiting/processing/failed/cancelled/completed 状态、租约、重试、取消和阶段可观测性。该 Run MUST 只执行修订草稿生成分支，不执行 answer 上下文决策、搜索、调查或工作集推进。

#### Scenario: Worker 执行修订 Run
- **WHEN** Worker 领取 waiting 的 entry_revision Run
- **THEN** 它校验关联 Draft 后执行 Evidence 复验与草稿模型，原子提交 Draft/Run/助手消息终态

#### Scenario: 修订 Run 崩溃恢复
- **WHEN** Worker 在模型调用边界退出且 Run 超过租约
- **THEN** 系统在重试上限内恢复同一 Run 与 Draft，不创建第二个 Draft 或重复消息

#### Scenario: 取消生成中的修订
- **WHEN** 用户取消 waiting/processing 的 entry_revision Run
- **THEN** Worker 在安全边界停止，Run/Draft 进入 cancelled，不修改 target Entry 或推进工作集

### Requirement: 修订生成与执行阶段可观测
系统 MUST 分别记录 entry revision 草稿模型、确认工具和撤销工具的 purpose、provider、model、fallback、error、duration 与结果摘要；响应成功 MUST NOT 掩盖模型降级、版本冲突、Evidence 失效或工具失败。

#### Scenario: 草稿模型成功
- **WHEN** entry_revision Run 生成合法草稿
- **THEN** 模型调用记录包含真实 provider/model/is_fallback/error 与耗时，Run 汇总可识别未降级成功

#### Scenario: 确认或撤销失败
- **WHEN** Entry 应用或撤销工具失败
- **THEN** 工具调用记录标记 error/真实状态，Execution 与界面不进入伪成功终态
