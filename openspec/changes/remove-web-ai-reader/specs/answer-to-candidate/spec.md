## REMOVED Requirements

### Requirement: 保存前可编辑
**Reason**: 本需求及其场景只由旧 Web「AI 阅读」的「保存为知识」入口承载，该入口随本次改动移除。
**Migration**: 保存前可编辑改由知识 Agent 的 `knowledge-agent-candidate-draft`「用户可编辑或取消未确认草稿」承担。

### Requirement: 创建虚拟 Source
**Reason**: 本需求绑定旧 Reader 的「AI 阅读问答」虚拟 Source 与客户端引用契约，旧 Reader 保存端点已移除。
**Migration**: 虚拟 Source 的创建改由 `knowledge-agent-candidate-draft`「确认只创建待确认 Candidate 且幂等」「Candidate 溯源和后续建议沿用既有闭环」承担，类型标识为「知识 Agent 对话」。

### Requirement: 回答转 Candidate
**Reason**: 本需求的场景描述旧 Web「AI 阅读回答保存」入口，入口已移除。
**Migration**: 回答转 Candidate 改由 `knowledge-agent-candidate-draft`「确认只创建待确认 Candidate 且幂等」承担。

### Requirement: 保存后目录推荐与关系判断
**Reason**: 本需求描述旧 Reader 保存后的目录推荐与关系判断，保存入口已移除。
**Migration**: 目录推荐与关系判断改由 `knowledge-agent-candidate-draft`「Candidate 溯源和后续建议沿用既有闭环」承担。

### Requirement: 引用校验
**Reason**: 本需求是旧 Reader 的客户端引用契约（客户端提交 `entry_id` / `source_id`），与知识 Agent 的 Run-backed Evidence 契约方向相反，入口已移除。
**Migration**: 引用可信性改由 `knowledge-agent-candidate-draft`「目标项目与 Evidence 由服务端约束」「确认只创建待确认 Candidate 且幂等」与 `answer-to-candidate`「Knowledge Agent 保存只信任 Run-backed Evidence」承担。

### Requirement: 旧 Reader 与 Knowledge Agent 复用 Candidate 创建服务
**Reason**: 旧 Reader 入口已移除，本需求标题与「旧 Reader 继续按既有请求校验后调用」的表述不再成立。
**Migration**: 共享创建服务的约束由本 change 新增的「Knowledge Agent 复用 Candidate 创建服务」承接。

## ADDED Requirements

### Requirement: Knowledge Agent 复用 Candidate 创建服务
系统 MUST 将虚拟 Source、Attachment、Extraction 和 pending Candidate 的创建收敛到可复用应用服务，由 Knowledge Agent 按 Draft/Run/Evidence 校验后调用；该入口 MUST 保持 Workspace 隔离与「不直接写 Entry」语义，且不得通过内部 HTTP 代理。

#### Scenario: Knowledge Agent 确认调用共享服务
- **WHEN** Knowledge Agent Draft 通过全部确认校验
- **THEN** 应用服务创建相同的领域对象，且来源元数据标识为 Knowledge Agent Conversation/Run

#### Scenario: 创建事务失败
- **WHEN** Source、Attachment、Extraction、Candidate 或 Draft 关联任一步骤提交失败
- **THEN** 事务不暴露半成品 Candidate，客户端可用相同幂等键安全恢复或重试
