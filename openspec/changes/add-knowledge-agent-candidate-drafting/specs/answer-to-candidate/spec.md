## ADDED Requirements

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
