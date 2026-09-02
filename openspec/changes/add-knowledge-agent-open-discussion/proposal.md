## Why

当前 Knowledge Agent 的回答仍以 Grove 正式知识检索为前提：没有可核验 Evidence 时通常只能返回知识不足，无法承接用户在尚无已有知识或明确任务时的解释、讨论与共同思考。下一阶段需要先建立开放讨论和透明依据契约，让 Agent 能按问题需要使用用户当前陈述、Grove 知识与模型通用能力，同时继续遵守范围隔离、可追溯、人在环上和禁止静默降级。

## What Changes

- 为普通回答增加受用户约束的依据策略：仅使用 Grove、Grove 优先、模型优先、混合依据或需要外部材料；界面只展示实际采用的依据，不向用户暴露内部规划枚举。
- 允许不调用 Grove 工具的模型通用讨论正常完成；没有 Citation 不再自动等于知识不足，回答状态改为按请求是否完成、是否存在缺口或执行失败判断。
- 将当前话题内用户明确陈述的消息作为可追踪的“用户提供的信息”参与后续分析，但不把它们包装成 Citation、Source 或正式 Entry，也不把历史助手回答升级为事实。
- 对每个回答持久化实际依据类型、Grove Evidence、用户陈述消息句柄、是否使用模型通用知识及外部材料边界，并在原生 App 回答下展示紧凑、可展开的依据概览。
- 增加下一条消息的一次性“仅使用我的知识库”覆盖；显式界面覆盖和用户自然语言限制优先于 Agent 自动规划。
- 保留 quick 与 investigate 的现有产品语义：显式深度查找仍必须执行受限 Grove 调查；自动模型优先回答不伪装成深度调查。
- 继续记录规划、检索、调查和回答阶段的 provider、model、fallback、错误、耗时和实际工具调用；依据规划或执行降级必须在 Run 与界面中可识别。
- 兼容旧历史消息、旧客户端、`draft_candidate` 和 pending Candidate；现有固定“整理成知识”只对能够由有效 Grove Evidence 完整支撑的旧式回答继续开放，不扩展到模型优先或混合依据回答。
- 建立覆盖开放讨论、知识优先、混合依据、严格用户限制、来源冲突、时效/高风险边界、失败降级和旧数据兼容的代表性评估集。

### 用户黄金路径

1. 用户在原生 App 询问一个无需个人知识的通用问题，Agent 不强制检索 Grove，直接用模型通用能力回答，并显示“AI 通用知识 · 未使用你的知识库 · 未检索实时外部资料”。
2. 用户在同一话题补充个人情况并要求结合某个项目记录，Agent 使用当前用户陈述、当前范围内重新核验的 Grove Evidence 和模型通用能力回答。
3. 回答下显示“你的知识 N 条 · 结合你提供的信息 · AI 通用知识补充”，Grove Citation 仍可打开 Entry 与 Source 原文，模型知识不生成 Citation。
4. 用户下一条选择“仅使用我的知识库”后，系统严格使用 Grove Evidence；没有足够证据时明确返回依据不足，不以模型通用知识补齐。
5. 整个流程可在断线、重启和历史分页后恢复生成时范围、回答状态、Citation、实际依据与降级信息。

### Non-Goals

- 不建设 `EntrySetSpec`、精确统计、结构化筛选、排序、分组或通用只读工具运行时。
- 不统一 quick 与 investigate 的长期工具执行器，不改变现有有界调查预算。
- 不实现讨论片段整理、`prepare_operation`、Operation Plan、Operation Review、主动沉淀建议或任何新的知识写入路径。
- 不接入实时外部搜索、专业数据工具或 Discovery，不把模型训练知识描述为当前外部材料。
- 不增加统一可信度、核验状态或“已验证事实”语义，不替用户判断 Source 是否可靠。
- 不移除旧 `draft_candidate` API、固定回答动作、历史 Candidate 或旧客户端兼容。
- 不接入 Web 对话界面，不实现移动、合并、回收站或多 Entry 操作。

## Capabilities

### New Capabilities

- `knowledge-agent-answer-basis`: 定义开放回答的依据策略、用户约束、实际形成依据、用户陈述边界、回答状态与诚实表达规则。

### Modified Capabilities

- `knowledge-agent-run`: 允许 Run 按依据策略选择不调用工具、现有 Grove 查询或混合回答，持久化请求/实际依据和开放回答结果，并扩充分阶段可观测性。
- `knowledge-agent-conversation`: 消息提交新增幂等的一次性依据覆盖，并在历史恢复中返回生成时的依据摘要。
- `knowledge-agent-follow-up`: 当前话题内被明确采用的用户消息可以作为“用户提供的信息”参与后续回答，同时维持历史助手回答不得成为事实或引用的边界。
- `knowledge-agent-investigation`: 明确深度查找仍代表实际执行受限 Grove 调查，并规定调查无证据时与模型通用回答、用户限制和降级状态的组合行为。
- `native-knowledge-agent-answer`: 支持无 Citation 的正常开放回答、紧凑依据概览、依据详情、外部材料边界和新的保存入口资格判断。
- `native-knowledge-agent-conversation`: 在现有模式控制中增加下一条消息的一次性“仅使用我的知识库”覆盖并稳定恢复历史依据。
- `knowledge-agent-candidate-draft`: 保持旧 `draft_candidate` 兼容，但只允许整理能够由来源 Run 的有效 Grove Evidence 完整支撑的内容，不把用户陈述或模型通用知识错误写入旧 Candidate 流程。

## Impact

- 后端知识 Agent 的消息请求、Run 持久化、回答结构、上下文处理、执行编排、可观测记录和历史序列化会增加依据相关字段与校验。
- 原生 App 的 Composer 模式 Sheet、回答卡、依据详情、历史恢复与固定“整理成知识”可用性会调整；缺少新字段的历史数据继续使用现有展示。
- 需要数据库迁移保存请求/实际依据和用户陈述句柄；迁移必须同时兼容 SQLite 与 MySQL 8，并提供旧记录的安全默认语义。
- 不改变 Workspace/项目范围模型、Entry/Source/Candidate 的正式数据关系，也不新增最终写入工具。
