# answer-to-candidate Specification

## Purpose
把 AI 阅读回答在确认前先编辑，保存为记录问题与回答原文的虚拟 Source 和待确认 Candidate，再进入既有确认流程。
## Requirements
### Requirement: 保存前可编辑
系统 MUST 在用户保存回答时先展示编辑框，允许修改标题与内容后再确认；用户未确认前 MUST NOT 创建任何 Source 或 Candidate。

#### Scenario: 编辑后保存
- **WHEN** 用户在 AI 阅读回答中点击「保存为知识」并修改标题与内容
- **THEN** 使用编辑后的标题与内容创建候选

#### Scenario: 未确认不创建
- **WHEN** 用户取消保存
- **THEN** 不创建任何 Source 或 Candidate

### Requirement: 创建虚拟 Source
系统 MUST 在确认保存后创建「AI 阅读问答」类型的虚拟 Source，归属当前项目与 Workspace；虚拟 Source MUST 记录原始问题与回答文本，作为候选可溯源的上下文。

#### Scenario: 虚拟 Source 承载问答
- **WHEN** 用户确认保存回答
- **THEN** 创建归属当前项目与 Workspace 的虚拟 Source，包含问题与回答原文

#### Scenario: Workspace 隔离
- **WHEN** 保存请求来自其他 Workspace 的项目
- **THEN** 请求失败（404），不创建任何数据

### Requirement: 回答转 Candidate
系统 MUST 把编辑后的回答创建为待采纳 Candidate，归属该虚拟 Source；Candidate 的主类型与信息性质 MUST 使用 AI 推荐值（推荐为空时主类型默认 knowledge）；Candidate 的证据 MUST 引用被引用 Entry 的原始 Source 证据（attachment 与原文片段）；候选进入确认台，等待用户确认后走既有归档流程。

#### Scenario: 候选进入确认台
- **WHEN** 回答保存成功
- **THEN** 创建待采纳 Candidate，使用 AI 推荐的主类型与信息性质，证据引用原始 Source 的 attachment 与原文片段

#### Scenario: 不直接写入 Entry
- **WHEN** 回答被保存为候选
- **THEN** 不创建或修改任何正式 Entry，正式归档仍由用户确认后完成

### Requirement: 保存后目录推荐与关系判断
系统 MUST 在创建 Candidate 后执行与普通采集候选一致的目录推荐与关系判断：为候选推荐目录节点并判断与已有 Entry 的关系；结果 MUST 落库并在确认台可见。

#### Scenario: 保存候选带目录推荐
- **WHEN** 回答保存成功
- **THEN** 候选获得目录节点推荐与关系判断结果，确认台可查看

#### Scenario: 无合适目录
- **WHEN** 目录推荐无法匹配现有节点
- **THEN** 候选标记为「暂无合适位置」并可建议新节点

### Requirement: 引用校验
系统 MUST 在保存请求中校验引用的 `entry_id` / `source_id` 属于当前 Workspace 与项目；非法或越权引用 MUST 使请求失败（400），不创建数据。

#### Scenario: 非法引用被拒绝
- **WHEN** 保存请求包含不属于当前项目或 Workspace 的引用
- **THEN** 请求失败（400），不创建任何数据

### Requirement: Knowledge Agent 保存只信任 Run-backed Evidence
Knowledge Agent Candidate 确认接口 MUST 从服务端 Draft、source Run 与 Evidence 解析来源，不接受客户端自由提交 entry_id、source_id、attachment_id、quote 或 Evidence handles；确认时 MUST 重新校验当前 Workspace、目标项目、Entry、Source、Attachment、quote 与内容指纹。

#### Scenario: 客户端伪造引用字段
- **WHEN** 新确认接口收到客户端额外提交的 Entry、Source、quote 或 Evidence handle
- **THEN** 系统忽略或拒绝这些字段，只使用 Draft 中服务端固化并重新核验的 Evidence

#### Scenario: Run Evidence 当前有效
- **WHEN** Draft 的 Evidence 仍属于目标项目且原文可核验
- **THEN** 系统用当前 attachment_id 与真实 quote 创建 Candidate evidence_refs

#### Scenario: 只有历史快照可用
- **WHEN** source Run citation 仍可展示但当前 Entry、Source 或 Attachment 已删除或内容指纹变化
- **THEN** 系统拒绝新 Candidate 写入，不把历史快照当作当前正式溯源

### Requirement: 旧 Reader 与 Knowledge Agent 复用 Candidate 创建服务
系统 MUST 将虚拟 Source、Attachment、Extraction 和 pending Candidate 的创建收敛到可复用应用服务；旧 Reader 继续按既有请求校验后调用，新 Knowledge Agent 按 Draft/Run/Evidence 校验后调用。两条入口 MUST 保持 Workspace 隔离和“不直接写 Entry”语义，且不得通过内部 HTTP 互相代理。

#### Scenario: 旧 Reader 保存保持兼容
- **WHEN** Web 旧 Reader 使用原请求保存合法回答
- **THEN** 接口响应和 Candidate/Source 语义保持兼容，不要求 knowledge source_run_id

#### Scenario: 新 Agent 确认调用共享服务
- **WHEN** Knowledge Agent Draft 通过全部确认校验
- **THEN** 应用服务创建相同领域对象，但来源元数据标识为 Knowledge Agent Conversation/Run

#### Scenario: 创建事务失败
- **WHEN** Source、Attachment、Extraction、Candidate 或 Draft 关联任一步骤提交失败
- **THEN** 事务不暴露半成品 Candidate，客户端可用相同幂等键安全恢复或重试

