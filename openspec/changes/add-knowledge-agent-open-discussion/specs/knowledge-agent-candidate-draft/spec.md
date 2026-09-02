## MODIFIED Requirements

### Requirement: 候选草稿只能由有证据回答显式发起
系统 MUST 只允许从有最终有效 Citation 且能够证明可整理内容未采用用户陈述、模型通用知识或外部材料的新回答显式发起旧 `draft_candidate`；本 change 上线前没有 basis 字段的历史回答 MUST 继续按既有最终 Citation 与 Evidence 复验规则判断。普通开放讨论、模型优先、混合依据或依赖外部材料的回答 MUST NOT 进入旧 Candidate Draft 流程，即使它们包含部分 Grove Citation。

#### Scenario: 从纯 Grove 有证据回答发起
- **WHEN** completed 来源回答的实际依据只有当前 Run 有效 Grove Evidence
- **THEN** 系统允许用户显式提交结构化 `draft_candidate` 动作，并只使用服务端复验后的 Evidence 生成草稿

#### Scenario: 纯 Grove partial 回答只整理可确认部分
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
