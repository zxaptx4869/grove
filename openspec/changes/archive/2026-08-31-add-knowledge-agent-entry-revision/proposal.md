## Why

知识 Agent 已能在原生 App 中连续阅读、受限调查，并把回答整理为待确认 Candidate；但用户仍不能在同一对话里明确选择一条正式 Entry、看懂修改差异、确认执行并在误操作后安全撤销。下一步需要用单对象、可逆的修订路径验证第二条知识操作黄金场景，同时复用 Grove 已有 Entry 版本历史与 AI 修订能力，而不是直接扩张到多 Entry 合并或任意增删改。

## What Changes

- 在有最终有效引用的 Knowledge Agent 回答中提供“修订这条知识”的 Entry 定向动作；目标必须来自该回答最终引用，普通 Composer 文本继续按只读问答处理。
- 新增持久化、可恢复的 Entry Revision Draft 与 operation Run：固化来源回答、目标 Entry、基线版本/快照、目标项目、允许 Evidence、候选字段、差异摘要、模型元数据、状态和执行结果。
- 草稿模型只基于目标 Entry 当前内容、用户明确指令、来源回答上下文和服务端允许的当前 Evidence 生成候选修订；不使用模型常识或联网内容补充事实。
- 原生 App 在对话中展示目标 Entry、AI 修订草稿、字段差异、编辑、执行后果、确认中、成功回执、撤销确认、撤销结果、版本冲突和失败重试；视觉与交互严格参考现有移动原型的草稿、完整差异、确认、执行回执和撤销路径，并裁剪为单 Entry 场景。
- 用户明确确认后，应用服务重新校验 owner、Workspace、项目、Entry 基线版本和 Evidence，在一个事务内更新一条 Entry、补充必要且去重的来源证据、追加版本并写入可审计执行记录；模型不能直接修改正式对象。
- 执行成功后允许对本次操作做一次安全、幂等撤销：只有 Entry 未发生后续修改时才恢复操作前字段并移除本操作新增的证据关系；若已出现后续版本则拒绝覆盖并引导查看版本历史。
- 记录草稿生成、确认执行和撤销的 provider/model/fallback/error、工具结果与耗时，禁止把降级、版本冲突、证据失效或部分失败静默包装为成功。

### Non-Goals

- 不处理上一轮代码审查发现的 Candidate 路由部分失败、空要点 completed、草稿 Evidence 范围扩大三个独立问题；它们由单独修复任务处理。
- 不实现自由文本写意图识别、任意工具循环或模型自行选择数据库写操作；首版只接受用户从明确 Entry 入口发起的结构化修订动作。
- 不创建新 Entry，不完成 Candidate 的移动端最终归档，不合并、标记重复、移动、删除或批量修改多个 Entry。
- 不实现原型中的多 Entry 影响对象、冲突批量处理和分步确认；它们属于下一条批量知识操作 change。
- 不允许 Knowledge Agent 修订使用 AI 自身知识或联网知识；现有桌面“AI 修订建议”的外部补充能力保持不变，但不直接复用其开放知识边界。
- 不迁移 Web 旧 Reader，不在 Web 新增统一知识 Agent 对话入口，也不接入移动端“收集 / 待处理 / 知识”其余栏目。
- 不建设通用写工具注册表、通用事务撤销框架或无限审计历史；只建立可被后续抽取复用的最小单 Entry 操作记录。

## Capabilities

### New Capabilities

- `knowledge-agent-entry-revision`: 锚定回答与单条正式 Entry 的持久修订草稿、基线冲突检测、Evidence 约束、确认执行、操作审计与安全撤销。
- `native-knowledge-agent-entry-revision`: 原生对话中的 Entry 定向修订入口、草稿编辑、字段差异、确认、执行回执、撤销、恢复与错误状态。

### Modified Capabilities

- `knowledge-agent-conversation`: 对话消息与历史增加显式 Entry 修订请求及关联修订草稿/执行状态，继续按用户与 Workspace 隔离。
- `knowledge-agent-run`: 固定执行图增加受控 `revise_entry` operation Run，并记录来源回答、目标 Entry、进度、模型与工具可观测性。
- `entry`: 用户确认的 Knowledge Agent 修订可复用 Entry 版本与证据服务更新一条正式知识，并提供只针对本次操作的并发安全撤销语义。
- `native-knowledge-agent-answer`: 有引用回答与引用详情增加明确 Entry 目标的结构化修订动作，不把普通讨论误判为修改。

## Impact

- 后端：扩展 Knowledge Agent 数据模型、schemas、Conversation/Run API、Worker 分支、Evidence 复验与消息历史归并；抽取或扩展 Entry 修订、版本、证据去重和恢复服务，并新增操作执行/撤销端点。
- 原生 App：扩展知识 Agent 类型、API、controller、消息归并和 query invalidation；新增单 Entry 修订草稿卡、编辑 Sheet、差异审阅、确认、回执与撤销组件。
- 数据与权限：新增持久修订草稿和执行记录；所有对象按 owner + Workspace 隔离，目标 Entry 固定在其所属项目，确认与撤销均进行乐观并发校验。
- 兼容性：现有只读回答、Candidate Draft、桌面 Entry 编辑/AI 修订/版本恢复和旧 Reader 行为保持兼容；无破坏性 API 变更。
