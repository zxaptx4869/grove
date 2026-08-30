## Why

只读 Knowledge Agent 已能在原生 App 中连续提问、受限调查并返回可核验引用，但用户还不能在同一对话里把有价值的回答转成待确认知识。下一步先交付风险最低的一条写操作纵向路径：由用户从某次有证据的回答明确发起，Agent 生成可编辑草稿，用户确认后只创建 Candidate，不直接改写正式 Entry。

## What Changes

- 在有最终有效引用的 `completed` / `partial` 回答上提供「整理成知识」动作；该动作作为一条可见用户消息提交，并创建锚定原回答 Run 的候选草稿 Run，不在客户端拼装或猜测来源。
- 项目范围回答默认以该项目为目标；Workspace「全部知识」回答必须先明确目标项目，并且草稿只可采用该项目内的有效 Evidence。多项目或目标不明确时先让用户选择，不静默跨项目写入。
- 新增持久化、可恢复的 Candidate Draft：保存来源 Run、目标项目、标题、内容、类型建议、采用的 Evidence 句柄、状态和最终 Candidate 关联；Agent 只生成草稿，用户可编辑或取消。
- 用户确认草稿后，由应用服务再次校验用户、Workspace、Conversation、Run、项目和 Evidence，幂等地创建「知识 Agent 对话」虚拟 Source、Attachment、Extraction 与待确认 Candidate；正式 Entry 仍须经过既有确认流程。
- 原生 App 在对话中展示动作入口、目标项目选择、草稿卡、编辑 Sheet、确认说明、创建中、成功回执与失败重试；视觉、信息层级和交互细节严格参考 `docs/prototypes/grove-mobile-agent-prototype.html` 的「整理成知识」路径，并在 design 中列出本 change 的有意裁剪。
- 记录草稿生成模型的 provider / model / fallback / error 与确认工具结果，禁止把模型不可用、Evidence 失效或路由失败静默包装为成功。

### Non-Goals

- 不创建、修改、移动、合并或删除正式 Entry，不把「创建 Candidate」表述为已经写入正式知识。
- 不实现原型中的主 Entry 更新、重复知识合并、完整差异审阅、正式知识撤销或操作审计中心；这些属于后续高风险写工具 change。
- 不在移动端实现 Candidate 的最终归档确认台、目录新建、关系处理或批量操作；本 change 的回执只说明 Candidate 已进入待确认状态。
- 不开放任意写工具循环，不让模型自行执行数据库写入，也不建设通用工具注册框架；首版只支持显式、锚定回答的 `draft_candidate` 操作。
- 不解析任意自由文本为写操作；普通 Composer 消息仍按只读问答处理，只有结构化动作入口提交候选草稿请求，避免讨论被误判为修改。
- 不迁移 Web 统一对话入口，不删除旧 Reader 与 `/reader/save-candidate` 兼容接口，不联网或使用模型常识补充草稿事实。

## Capabilities

### New Capabilities

- `knowledge-agent-candidate-draft`: 锚定回答 Run 的 Candidate 草稿生成、项目/Evidence 边界、编辑、取消、幂等确认与 Candidate 回执。
- `native-knowledge-agent-candidate-draft`: 原生对话中的整理入口、项目选择、草稿编辑、确认、恢复、错误与待确认回执。

### Modified Capabilities

- `knowledge-agent-conversation`: 对话消息与历史可承载显式候选草稿请求及关联草稿状态，且继续按用户与 Workspace 隔离。
- `knowledge-agent-run`: 固定执行图增加受控 `draft_candidate` 分支，持久化操作类型、来源 Run、进度和模型/工具可观测性。
- `answer-to-candidate`: 保存链路改为可复用的 Run-backed 应用服务，确认时只信任服务端 Evidence 与目标项目，并保持旧 Reader 兼容行为。
- `native-knowledge-agent-answer`: 有证据回答增加结构化后续动作，并明确知识回答、AI 草稿、Candidate 回执三种语义和状态。

## Impact

- 后端：新增 Candidate Draft 模型与 Alembic 迁移；扩展知识 Agent schemas、Conversation/Run API、Worker 执行分支、模型调用、Evidence 校验与可观测记录；抽取旧 Reader 保存逻辑中的可复用 Candidate 创建服务。
- 原生 App：扩展领域类型、API、query keys/controller 与消息归并；新增目标项目选择、草稿卡、编辑/确认 Sheet 和回执组件，并补齐恢复、幂等与错误状态。
- 数据与权限：所有 Draft、Run、Source、Extraction、Candidate 和 Evidence 校验继续按 owner + Workspace 隔离；目标项目必须属于当前 Workspace，确认前不创建 Source/Candidate。
- 兼容性：旧 Web Reader 保存接口继续可用；现有只读回答、追问、调查和历史协议保持默认行为。
