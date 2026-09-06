## MODIFIED Requirements

### Requirement: 普通回答按用户约束选择形成依据

系统 MUST 在 `actual_result_mode=answer` 时尊重用户显式依据覆盖和当前消息中的明确限制。启用复合回答的 quick Run MUST 为每项回答义务分别选择 `grove_only`、`grove_required`、`model_allowed` 或 `external_required`，而不是要求整条消息只有一个内部依据策略；未启用复合回答或 investigate Run 可以继续使用兼容策略 `knowledge_only`、`knowledge_first`、`model_first`、`hybrid` 或 `external_needed`。任何策略 MUST NOT 自行放宽限制、指定 Workspace/项目或获得写权限，结构化 Entry 结果 MUST NOT 执行回答依据规划。

#### Scenario: 通用解释使用模型知识
- **WHEN** 用户以自动依据模式询问无需个人知识或实时材料的通用概念
- **THEN** quick 复合计划可以生成单个 `model_allowed` 义务、不调用 Grove 工具并使用模型通用能力回答；兼容路径可以选择 `model_first`

#### Scenario: 个性化问题读取 Grove
- **WHEN** 用户询问自己的项目记录、历史决定或已有经验
- **THEN** 对应回答义务要求 Grove，并只在 Run 固化的 Workspace/项目范围内读取正式知识

#### Scenario: 一条消息使用多种依据
- **WHEN** 用户要求先解释一般概念，再结合个人知识分析来源和等级
- **THEN** 系统允许概念义务使用模型知识、个人部分要求 Grove，并在同一回答中分别保存实际依据和覆盖结果

#### Scenario: 显式仅使用个人知识库
- **WHEN** 用户通过结构化覆盖选择“仅使用我的知识库”
- **THEN** 系统把全部回答义务固定为 `grove_only`，兼容路径固定 `knowledge_only`，不得允许规划器或回答器引入模型通用知识或外部材料

#### Scenario: 自然语言限制收紧策略
- **WHEN** 自动依据请求中明确写出“只根据我的知识库回答”或等价限制
- **THEN** 服务端将全部逐项策略收紧为 `grove_only`，兼容规划结果收紧为 `knowledge_only`，即使模型认为通用知识有帮助也不得放宽

#### Scenario: 依据规划失败
- **WHEN** 复合或兼容依据规划模型未配置、超时、调用失败或返回非法结构
- **THEN** 系统显式记录对应 fallback 并在保持用户显式限制的前提下选择兼容路径；没有显式允许模型能力时不得静默改用模型通用知识，用户明确禁止 Grove 时不得回退检索 Grove

#### Scenario: 仅用通用知识不是仅用知识库
- **WHEN** 用户说只用通用知识或不查我的知识库
- **THEN** 系统不得因含有知识一词将其识别为 grove_only，不调用 Grove 查询工具，并正确标记模型依据

#### Scenario: 对话继承依据限制
- **WHEN** 用户继续要求简写或解释刚才的通用讨论，且未修改依据限制
- **THEN** 本轮保持该限制，历史助手只用于理解意图，不成为正式知识或用户陈述

#### Scenario: 恢复任务时隔离中间讨论
- **WHEN** 用户从中间话题恢复之前的查询或讨论任务
- **THEN** 系统只继承选定任务的依据限制与合法用户陈述，并合并本轮明确限制及界面覆盖；中间任务的陈述、助手回答和 Evidence 不自动进入本轮依据

#### Scenario: 任务池不扩大事实输入
- **WHEN** 上下文决策读取多个近期任务及其意图线索供选择
- **THEN** 回答依据仍只接收服务端验证的本轮任务消息和当前 Run Evidence，模型不能将其他任务消息句柄自行加入允许集合
