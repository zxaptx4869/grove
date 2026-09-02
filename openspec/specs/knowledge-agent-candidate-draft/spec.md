# knowledge-agent-candidate-draft Specification

## Purpose
TBD - created by archiving change add-knowledge-agent-candidate-drafting. Update Purpose after archive.
## Requirements
### Requirement: 候选草稿只能由有证据回答显式发起
系统 MUST 只允许从有最终有效 Citation 且能够证明可整理内容未采用用户陈述、模型通用知识或外部材料的新回答显式发起旧 `draft_candidate`；本 change 上线前没有 basis 字段的历史回答 MUST 继续按既有最终 Citation 与 Evidence 复验规则判断。普通开放讨论、模型优先、混合依据或依赖外部材料的回答 MUST NOT 进入旧 Candidate Draft 流程，即使它们包含部分 Grove Citation。

#### Scenario: 从有证据回答发起
- **WHEN** completed 来源回答的实际依据只有当前 Run 有效 Grove Evidence
- **THEN** 系统允许用户显式提交结构化 `draft_candidate` 动作，并只使用服务端复验后的 Evidence 生成草稿

#### Scenario: 部分回答只整理可确认部分
- **WHEN** partial 来源回答仍有完全由有效 Grove Evidence 支持的可整理内容
- **THEN** 系统只允许对应 Evidence 进入 Draft，未解决 gaps 与失效内容不得进入候选事实

#### Scenario: 模型优先回答
- **WHEN** 来源回答没有 Citation且实际依据包含模型通用知识或用户陈述
- **THEN** 系统拒绝旧 `draft_candidate`，不创建 Run、Draft、Source 或 Candidate

#### Scenario: 混合回答含部分 Citation
- **WHEN** 来源回答同时使用 Grove Citation 与用户陈述或模型通用知识
- **THEN** 系统拒绝旧 `draft_candidate`，不得只凭 Citation 非空截断或猜测可保存内容

#### Scenario: 历史有证据回答
- **WHEN** 来源 Run 创建于本 change 上线前、没有 basis 字段但有旧协议下的最终有效 Citation
- **THEN** 系统继续按旧 Evidence 复验规则允许整理，保持历史入口和 pending Candidate 兼容

#### Scenario: 知识不足或无引用回答
- **WHEN** 来源回答为 insufficient、failed、clarification 或没有满足兼容规则的有效 Citation
- **THEN** 系统拒绝操作且不创建 Draft

#### Scenario: 普通消息讨论保存
- **WHEN** 用户在普通 Composer 消息中询问“这个能保存吗”且未提交结构化 `draft_candidate` 动作
- **THEN** 系统仍按只读回答处理，不创建 Candidate Draft、Source 或 Candidate

### Requirement: 目标项目与 Evidence 由服务端约束
系统 MUST 由 source Run 范围和最终 citations 确定可选目标项目；项目范围回答 MUST 固定为该项目，Workspace 回答跨多个项目时 MUST 先由用户选择当前 Workspace 内一个目标项目。草稿生成和确认只能采用目标项目内当前仍可核验的 Run Evidence，模型与客户端不得指定 Workspace、任意对象 ID 或范围外句柄。

#### Scenario: 项目范围自动确定目标
- **WHEN** source Run 固化范围为当前 Workspace 的一个项目
- **THEN** Draft 固化同一 target_project_id，客户端不能替换为其他项目

#### Scenario: Workspace 回答只命中一个项目
- **WHEN** source Run 为全部知识且最终有效 citations 全部属于同一项目
- **THEN** 系统可预填该项目为唯一目标并只采用该项目 Evidence

#### Scenario: Workspace 回答命中多个项目
- **WHEN** source Run 的最终有效 citations 来自多个项目
- **THEN** 系统要求用户先选择其中当前可用的目标项目，选择前不创建 operation Run 或 Draft

#### Scenario: 目标项目没有可用 Evidence
- **WHEN** 所选项目的 citations 已删除、移出范围、来源失效或原文指纹无法核验
- **THEN** 系统返回可恢复冲突且不生成无来源草稿

#### Scenario: 越权来源 Run 或项目
- **WHEN** 用户提交其他用户、Workspace、Conversation 的 source_run_id 或越权 target_project_id
- **THEN** 系统返回 404 且不暴露对象是否存在

### Requirement: Candidate Draft 持久化且可恢复
系统 MUST 持久化 Draft 的 owner、Workspace、Conversation、operation Run、source Run、目标项目快照、标题、内容、类型建议、Evidence 句柄、生成可观测信息、状态和确认结果；Draft 状态 MUST 限定为 generating、draft、confirming、confirmed、cancelled、failed，并按合法路径转换。消息历史 MUST 能规范化返回关联 Draft，使客户端重启后恢复真实状态。

#### Scenario: 草稿生成中重启 App
- **WHEN** Draft 仍为 generating 且客户端退出后重新打开 Conversation
- **THEN** 消息页返回 operation Run 与 Draft，客户端恢复生成进度而不重复提交动作

#### Scenario: 草稿生成完成
- **WHEN** operation Run 成功生成并校验结构化草稿
- **THEN** 系统原子保存 Draft 内容、completed Run、助手说明并释放会话活动槽

#### Scenario: 草稿 Run 崩溃恢复
- **WHEN** Worker 在生成模型调用前后退出且 Run 超过租约
- **THEN** 系统在重试上限内恢复同一 operation Run 和 Draft，不创建第二个 Draft

#### Scenario: 非法状态转换
- **WHEN** confirmed 或 cancelled Draft 被再次改回 draft
- **THEN** 系统拒绝转换并保留原状态与确认关联

### Requirement: 草稿内容只能从受限 Evidence 生成
系统 MUST 用原问题、原回答编辑上下文、目标项目和服务端允许的 Evidence 生成结构化 title、content、main_type、info_nature 与 selected Evidence handles；最终句柄 MUST 属于允许集合、去重且至少有一条。模型输出只能生成草稿，MUST NOT 创建 Source、Candidate、Entry 或目录。

#### Scenario: 模型生成合法草稿
- **WHEN** 模型返回合法字段和允许的 Evidence handles
- **THEN** 系统保存可编辑 Draft 并记录实际 provider/model/is_fallback/error

#### Scenario: 模型返回未知句柄
- **WHEN** 模型混入其他 Run、其他项目或未知 Evidence handle
- **THEN** 系统丢弃非法句柄；剩余句柄不足时草稿失败且不伪造引用

#### Scenario: 模型服务不可用
- **WHEN** 草稿模型未配置、超时、失败或输出非法结构
- **THEN** 系统记录明确降级或失败；若使用原回答生成确定性可编辑 seed，界面必须标识降级且仍只绑定有效 Evidence

#### Scenario: 模型尝试执行写入
- **WHEN** 模型输出 Candidate、Entry、目录或项目对象标识或要求直接执行数据库动作
- **THEN** 应用忽略越权字段，只保留草稿 schema 内合法字段且不写正式对象

### Requirement: 用户可编辑或取消未确认草稿
系统 MUST 允许 Draft 所有者在 draft 状态编辑标题、内容、main_type 与 info_nature，或取消 Draft；目标项目、source Run 和 Evidence 集合 MUST NOT 由客户端编辑。取消或离开编辑界面 MUST NOT 创建 Source、Extraction、Candidate 或 Entry。

#### Scenario: 编辑草稿字段
- **WHEN** 用户修改合法标题、内容和类型建议
- **THEN** 系统保存编辑值并在历史恢复时返回最新版本

#### Scenario: 编辑受保护字段
- **WHEN** 客户端尝试修改 target_project_id、source_run_id 或 Evidence handles
- **THEN** 系统拒绝请求且不改变 Draft

#### Scenario: 取消草稿
- **WHEN** 用户取消尚未确认的 Draft
- **THEN** Draft 进入 cancelled，保留审计但不创建任何知识对象

#### Scenario: 编辑已确认草稿
- **WHEN** 用户尝试编辑 confirmed Draft
- **THEN** 系统返回冲突并返回已创建 Candidate 关联

### Requirement: 确认只创建待确认 Candidate 且幂等
系统 MUST 仅在用户明确确认 draft 状态对象后，由应用服务再次校验 owner、Workspace、目标项目和当前 Evidence，并在一个事务中创建可溯源虚拟 Source、Attachment、Extraction 与 pending Candidate；MUST NOT 创建或修改正式 Entry。确认 MUST 使用稳定 client_operation_id 幂等，Draft MUST 保存唯一 confirmed_candidate_id。

#### Scenario: 首次确认草稿
- **WHEN** 用户确认合法 Draft
- **THEN** 系统创建一组虚拟 Source/Attachment/Extraction 和一个 pending Candidate，写回 confirmed_candidate_id 并返回待确认回执

#### Scenario: 网络未知后重试
- **WHEN** 首次确认已成功但响应丢失，客户端用相同 client_operation_id 重试
- **THEN** 系统返回同一 Candidate，不重复创建 Source、Extraction 或 Candidate

#### Scenario: 并发确认同一草稿
- **WHEN** 两个请求同时确认同一 Draft
- **THEN** 数据库约束与事务锁保证最多创建一个 Candidate，另一个请求返回同一结果或稳定冲突

#### Scenario: 确认前 Evidence 失效
- **WHEN** Draft 生成后 Entry、Source、Attachment、项目归属或原文指纹发生变化而无法重新核验
- **THEN** 系统返回 409、保留未确认 Draft 并要求重新生成，不用历史快照创建新 Candidate

#### Scenario: 不直接写入正式知识
- **WHEN** Draft 确认成功
- **THEN** 回执明确 Candidate 仍待确认，数据库不新增或修改 Entry

### Requirement: Candidate 溯源和后续建议沿用既有闭环
系统 MUST 让虚拟 Source 记录原问题、原回答、用户编辑后的草稿、source Run 与目标项目；Candidate evidence_refs MUST 由服务端当前 Evidence 的 attachment_id 与真实 quote 构造。创建后 MUST 复用既有目录推荐和 Entry 关系判断能力，并显式保留 pending、失败或降级状态。

#### Scenario: Candidate 保留对话来源
- **WHEN** 用户确认 Candidate Draft
- **THEN** Source/Attachment 能追溯 source Run、原问题、原回答、编辑内容和采用的当前原文 Evidence

#### Scenario: 目录与关系建议成功
- **WHEN** Candidate 创建后既有路由与关系服务成功
- **THEN** Candidate 返回真实 routing_status、recommended_node 与 relation_status，仍等待人工确认

#### Scenario: 辅助建议失败
- **WHEN** Candidate 已创建但目录推荐或关系判断失败
- **THEN** 系统保留 Candidate 并记录/返回真实 pending 或失败影响，不把辅助阶段伪装为正常，也不回滚为无记录

