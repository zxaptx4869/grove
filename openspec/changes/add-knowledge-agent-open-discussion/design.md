## Context

当前 `KnowledgeAgentRun` 在上下文决策与结果形态路由后，只能进入结构化 Entry 查找、quick 固定检索图或 investigate 有界调查图。综合回答器的提示与 `build_validated_answer` 都要求事实性要点具有当前 Run Evidence；搜索为空或全部引用失效时返回知识不足。这个契约保证了 Grove 引用可信，却也使普通解释、头脑风暴和无已有知识的讨论无法成立。

本 change 需要在不削弱现有 Evidence 边界的前提下增加开放回答：模型可以使用当前话题中的用户陈述和模型通用能力，相关时继续读取 Grove。它横跨数据库、PydanticAI 规划与回答模型、Run 执行器、历史 API、原生 App 和旧 Candidate Draft 资格判断，因此需要显式设计迁移、降级与兼容方案。

现有关键扩展点包括：

- `backend/app/models/knowledge_agent.py` 的 Run、Message、工具调用与模型调用记录；
- `backend/app/services/knowledge_agent/runner.py` 的上下文、结果形态、回答模式和 quick 执行图；
- `backend/app/services/knowledge_agent/investigation_runner.py` 的有界调查与综合；
- `backend/app/agents/knowledge_agent.py` 与 `build_validated_answer` 的回答草与引用校验；
- `backend/app/services/knowledge_agent/candidate.py` 的来源 Candidate Draft 来源 Run 校验；
- `mobile/src/knowledge-agent` 的领域类型、一次性模式、回答卡、来源 Sheet 和历史恢复。

## Goals / Non-Goals

**Goals:**

- 让普通回答在 `knowledge_only`、`knowledge_first`、`model_first`、`hybrid`、`external_needed` 五种内部策略下执行，并由服务端保存实际规划策略与实际形成依据。
- 只向用户提供“自动选择”和“仅使用我的知识库”两种依据模式；自然语言中的明确限制同样生效，显式界面覆盖优先。
- 允许模型优先回答在没有 Citation 时正常 `completed`，同时继续保证所有 Grove Citation 都来自当前 Run 实际读取并核验的 Evidence。
- 允许当前话题中服务端校验过的用户消息作为个人前提参与回答，并能从历史 Run 还原实际采用的消息句柄。
- 保持 quick/investigate、工作集、范围隔离、取消恢复、幂等、分阶段可观测与旧数据兼容。
- 在原生 App 展示紧凑依据概览和可展开详情，不把回答、模型知识或用户陈述包装成正式 Entry/Source。

**Non-Goals:**

- 不引入通用只读工具运行时、结构化聚合、外部搜索或新的写入工具。
- 不实现讨论沉淀、Operation Plan/Review、主动建议或 Web 对话界面。
- 不改变 Entry、Source、Candidate 的正式对象定义，不增加可信度或事实核验状态。
- 不删除旧 `draft_candidate`、pending Candidate、历史回答或旧客户端支持。

## Decisions

### 1. 将依据规划放在结果形态之后、回答模式之前

回答执行顺序调整为：

```text
上下文决策
  → 结果形态路由
  ├─ entries：沿用现有结构化 Entry 查找，不执行依据规划
  └─ answer：解析用户依据限制并执行依据规划
       → 回答模式解析
       → model-only / quick Grove / investigate Grove
       → 基于允许依据生成回答
       → 服务端校验引用与实际依据
       → 原子提交
```

依据规划器只返回结构化决策：内部策略、允许使用模型通用知识、是否需要 Grove、是否需要但缺少外部材料、候选用户消息 ID。它不能指定 Workspace、项目、Entry、Source、Evidence 句柄、工具预算或写操作。

`request_basis_mode` 只有 `auto` 与 `knowledge_only`。新客户端必须显式发送默认 `auto`；缺少该字段的旧客户端按兼容的 `knowledge_only` 处理，避免旧界面无法展示依据时意外收到开放回答。当用户显式选择 `knowledge_only` 时，应用直接固化限制，不允许规划器放宽；服务端先用确定性规则识别“只根据我的知识库”等明确限制，再让规划器处理更广泛的自然语言表达，并始终取两者中更严格的结果。自动规划失败时显式 fallback 到 `knowledge_only`，复用当前最保守的 Grove-only 行为，而不是静默开放模型知识。

**替代方案：**把依据选择并入现有结果形态或回答模式路由。未采用，因为“用户想看到回答还是对象”“允许使用哪些依据”“愿意花多少调查成本”是三个正交契约，合并会重新形成难维护的细粒度路由器。

### 2. 区分规划策略与服务端确认的实际依据

为 `knowledge_agent_runs` 增加可空的 `request_basis_mode`、`planned_basis_strategy` 与 `answer_basis_json`：

```text
AnswerBasis v1
├─ schema_version
├─ grove
│  ├─ used
│  ├─ citation_count
│  └─ entry_count
├─ user_statements
│  └─ message_ids
├─ model_knowledge
│  └─ used
└─ external_material
   └─ status: not_used / required_unavailable
```

`planned_basis_strategy` 记录规划结果，`answer_basis_json` 记录最终回答实际允许并采用的形成依据。Grove 数量从最终通过校验的 Citation 派生；用户陈述 ID 从服务端允许集合与规划器选择的交集派生；模型知识是否使用由实际执行分支和提示权限保守标记，不依赖模型自由文本自报；外部状态只能由服务端根据规划结果写为“未使用”或“需要但当前不可用”。

不复制 Entry/Source 原文或整条用户消息到 `answer_basis_json`。历史 API 按消息 ID 读取同一 Conversation 中的用户消息并输出必要的短摘要；Citation 继续复用现有 Evidence 快照。这样既可恢复，又避免形成第二份不可同步的来源文本。

**替代方案：**把所有依据只写进 `answer_json`。未采用，因为 Run 需要在回答失败、部分完成和旧客户端忽略回答扩展字段时仍能审计规划与实际依据，且后续 Operation formation basis 需要复用稳定的 Run 级协议。

### 3. 用户陈述只来自当前话题的有界消息集合

服务端在上下文决策后构造允许的用户陈述集合：当前用户消息始终可选；`continue` 只追加同一 Conversation、同一范围快照、当前活动上下文链内的近期用户消息，并受数量和单条长度上限约束。`new_topic`、范围切换和澄清未完成都不继承旧话题陈述。

规划器只能返回服务端提供的消息句柄；未知 ID、助手消息、系统消息、其他 Conversation、其他 Workspace/项目或超出有界集合的消息全部丢弃并记录异常。用户陈述在回答中只能表达为“你提供的信息”，不能生成 Grove Citation、Source quote 或工作集 Entry。

现有工作集继续只保存正式 Entry 线索。模型-only 回答可按现有规则建立只含主题标签的上下文版本，但不得添加虚构 Entry；混合回答仍只把最终有效 Citation 对应的 Entry 加入输出工作集。

**替代方案：**把整段历史直接加入回答上下文。未采用，因为这会破坏现有“历史助手回答不是事实”的边界，并使长对话成本、范围漂移和错误累积不可控。

### 4. 使用一个依据感知回答器，但由服务端执行不同强度的校验

扩展现有结构化回答草稿，使回答要点可以携带零个或多个 Evidence 句柄；回答器同时接收：独立问题、范围、允许的用户陈述、可用 Grove Evidence、是否允许模型通用知识和外部材料边界。提示必须要求正文直接回答、不得伪造 Citation、不得声称联网，并在用户陈述与 Grove Entry 冲突时并列说明。

最终校验按请求边界执行：

- `knowledge_only`：所有保留的知识性要点必须具有当前 Run 有效 Evidence；无有效核心证据时为 `insufficient`。
- 允许模型知识的分支：无 Citation 的要点可以保留；任何模型生成的未知 Evidence 句柄仍被丢弃，Grove Citation 仍只从服务端 Evidence 派生。
- `knowledge_first` 或 `hybrid` 缺少计划需要的 Grove 依据时，可以保留一般分析，但必须在 basis/gaps 中说明未找到相关个人知识；是否 `partial` 或 `insufficient` 由核心请求是否完成决定。
- `external_needed` 不得伪造当前材料；只能给一般框架。核心问题依赖当前材料且未回答时为 `insufficient`，仅部分可回答时为 `partial`。

`completed`、`partial`、`insufficient` 与 `failed` 继续由服务端确定，不采用模型自报状态。没有 Citation 本身不再决定状态。

**替代方案：**为 Grove-only 与开放讨论维护两套回答模型和响应结构。未采用，因为两套回答器会让引用、冲突、结构化要点、错误恢复和移动端渲染长期分叉；同一草稿结构配合服务端策略校验更容易保持一致。

### 5. 第一阶段继续复用现有固定检索图

本 change 不提前实现阶段 B 的通用工具运行时：

- `model_first` 且未显式请求 investigate：跳过 Grove 搜索、Entry/Evidence 读取，直接进入依据感知回答器，`actual_answer_mode=quick`。
- `knowledge_only`、`knowledge_first`、`hybrid`：quick 继续使用现有搜索→Entry→Evidence 固定图。
- 用户显式 `investigate`：必须创建并执行现有有界 Grove 调查；规划器不能把它降成未执行工具的模型-only 回答。
- 自动模式下规划为 `model_first`：不调用 investigate 路由并确定性使用 quick；可观测记录不得伪造未发生的路由调用。
- 调查未找到 Evidence 时，如果用户允许模型知识，仍可在明确“未在你的知识中找到相关内容”的前提下生成一般回答；`knowledge_only` 则保持知识不足。

**替代方案：**先实现通用工具规划器。未采用，因为开放讨论不依赖计数、筛选或聚合工具；先验证开放回答的产品价值可以缩小首个 change 的风险。

### 6. 依据概览由服务端结构化输出，原生端只负责展示

Run/Message API 增加可选的请求依据模式、规划策略（仅诊断需要时返回）与结构化 `answer_basis`。原生端不解析回答正文判断来源，按结构化字段渲染：

- `你的知识 N 条`；
- `结合你提供的 N 条信息`；
- `AI 通用知识补充`；
- `未检索实时外部资料` 或 `当前需要外部材料`。

回答卡默认显示一行紧凑概览；有 Citation、用户陈述或外部边界时可展开依据详情。Grove 项继续打开现有 Citation Sheet；用户陈述显示短摘要并可定位到对应消息；模型知识只说明性质，不生成伪来源链接。缺少 `answer_basis` 的历史回答维持现有来源条和状态展示，不反向猜测完整形成依据。

原生 Composer 的现有 Mode Sheet 增加“依据”分组，只显示“自动选择”和“仅使用我的知识库”。非默认值使用现有一次性 Chip 语义，提交成功后重置；网络结果未知的重试必须复用同一值和 `client_message_id`。

### 7. 旧 Candidate Draft 只接受纯 Grove 或可信旧记录

服务端而非客户端决定固定“整理成知识”的资格：

- 新 Run 只有 `request_basis_mode/planned_basis_strategy/answer_basis` 能证明回答未采用用户陈述、模型通用知识或外部材料，且存在当前有效 Citation 时才可发起旧 `draft_candidate`；实际实现优先以 `knowledge_only` 为可证明的纯 Grove 路径。
- 新的 `model_first`、`hybrid` 以及使用用户陈述的回答即使含 Citation，也拒绝旧整理入口，因为旧流程无法保存完整 formation basis。
- change 上线前的历史 Run 没有 basis 字段；它们继续按旧规则以最终 Citation 与 Evidence 复验判断，保证历史入口和 pending Candidate 可用。
- 客户端可以提前隐藏不合格入口，但服务端必须再次校验，不能信任客户端判断。

此 change 不创建对话 Source，也不把开放回答内容塞进旧 Candidate。后续 `prepare_operation` change 再替代这条过渡路径。

### 8. 可观测性新增依据规划阶段并禁止静默降级

新增模型调用用途与步骤 `basis_route`，记录 prompt 版本、provider、model、fallback、错误、耗时和使用量。Run 的降级摘要同时包含依据规划、现有检索/调查和回答阶段。

关键规则：

- 依据规划失败回退 `knowledge_only` 时，回答即使成功也必须显示该阶段降级；
- 正常选择不调用 Grove 不是 fallback，也不写伪工具调用；
- Grove 搜索正常空结果记录 `empty`，与工具错误区分；
- 回答模型不可用时不得用静态模板伪装正常 AI 回答；有可展示的工具结果时可 `partial`，否则 `failed`；
- provider、model 和原始错误保留在审计接口，普通用户界面只显示受影响阶段和结果边界。

### 9. 使用特性开关与代表性评估集控制上线

增加服务端 `knowledge_agent_open_discussion_enabled`。关闭时完全沿用当前 Grove-only 执行图和响应；开启时接受新 basis 请求并执行新规划。数据库与 API 字段保持向后兼容，使新旧客户端可以交错部署。

评估集至少覆盖模型优先、知识优先、混合依据、严格用户限制、冲突、时效/高风险、失败降级和旧数据兼容。以下为硬门禁：伪造 Citation、突破 `knowledge_only`、跨 Workspace/项目读取、静默降级、把模型知识描述成实时外部结果的数量均必须为零。策略质量使用代表性样例人工复核，不引入模型自报的伪精确可信度。

## Risks / Trade-offs

- [依据规划器误把个性化问题选为 `model_first`] → 显式用户限制优先；规划提示包含“我的项目/记录/以前决定”等强信号；评估集覆盖同义表达；失败默认回退 Grove-only。
- [允许无引用要点后弱化 Citation 边界] → 只放宽正文是否必须引用，不放宽 Evidence 句柄校验；Grove 标签、引用数量和 Source 原文仍完全由服务端派生。
- [难以精确判断模型是否用了通用知识] → 按执行分支与提示权限保守标记；允许模型通用知识即展示该依据，宁可多提示，不让模型自行隐藏。
- [当前话题用户陈述被错误跨话题复用] → 只使用服务端有界集合、上下文链和范围快照；new_topic/范围切换切断；保存实际消息 ID 供测试和审计。
- [开放回答使旧“整理成知识”产生不完整来源] → 新 Run 只允许可证明的纯 Grove 回答进入旧流程；历史 Run 沿用旧证据规则；混合沉淀留给后续 Operation Plan。
- [新增规划调用增加延迟和成本] → model-first 跳过搜索/重排可抵消部分成本；保持单次结构化规划；记录阶段耗时与 usage，在真实评估后再调预算。
- [自动模式与显式深度查找发生语义冲突] → 显式 investigate 强制实际 Grove 调查；实际模式和停止原因可见，不能把纯模型生成包装为调查。
- [旧客户端无法展示 basis] → 所有新字段可选且响应加法兼容；旧客户端仍显示正文、状态与 Citation，不依赖新字段才能完成会话。

## Migration Plan

1. 新增可空 Run 字段与服务端枚举，Alembic 升级同时支持 SQLite 和 MySQL 8；旧记录不回填猜测依据。
2. 在特性开关关闭状态部署后端：新 API 字段可选，新客户端显式提交 `auto`，缺少字段的旧请求按 `knowledge_only` 执行并保持当前 Grove-only 行为。
3. 部署原生 App 的可选字段解析、依据模式、依据概览和服务端资格响应；旧服务端缺字段时沿用原展示。
4. 完成后端单元/集成测试、原生组件与控制器测试、代表性评估集和三视口手动走查后开启特性开关。
5. 观察 basis 策略、工具调用、fallback、空结果与回答状态分布；异常时关闭开关即可恢复旧执行图，保留新增字段用于审计。
6. 回滚不删除新增列或历史 basis 数据；旧 Candidate、历史消息和 pending Candidate 始终保留。

## Open Questions

没有阻塞 proposal 的产品问题。具体规划提示版本、模型参数、消息数量上限、摘要长度和依据概览短文案在实施中依据现有配置与评估结果确定，但不得改变本设计的用户限制优先级、Citation 边界、深度查找含义和旧流程兼容要求。
