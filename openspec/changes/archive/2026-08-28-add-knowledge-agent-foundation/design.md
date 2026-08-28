## Context

现有 Reader 是同步、单轮的项目/节点问答：前端临时保存消息，后端只接收当前问题，按一次召回、一次重排、一次生成返回答案。它已经具备 Workspace 鉴权和正式 Entry 召回，但模型生成的 `quote` 只校验 Entry/Source 标识，不会回到真实 Attachment 文本核对，因此不能作为长期对话和移动端恢复的可信基础。

原生移动端基础工程、Bearer 鉴权与真实项目范围选择已经完成。后续 Web 和 App 都需要使用同一套知识 Agent 协议，而不是各自封装 Reader。这个 change 先实现第一条可验证纵向链路：用户在 Workspace 或项目范围内提交一个独立问题，后台持久化执行只读检索，返回带真实来源证据的回答。连续追问、规划循环和写知识能力留给后续 change。

约束包括：

- 所有数据和工具访问均按当前用户的 Workspace 隔离，不能把模型参数作为可信范围。
- 回答可以直接返回给用户，但它不是正式 Entry；只有经现有候选确认链路才能进入知识库。
- SQLite 与 MySQL 8 都必须支持数据约束和 Worker 领取策略。
- 不引入外部队列、流式传输或新 AI SDK；复用当前进程内 Worker、混合检索和 `AIProvider`。
- AI 的搜索、重排和回答阶段均必须记录 provider、model、fallback 与错误，不能只在最终回答记录一次。

## Goals / Non-Goals

**Goals:**

- 建立可持久化、可恢复、可轮询的知识对话、消息和只读 Agent Run。
- 提供 Workspace/项目两级用户范围，目录只用于 Agent 内部定位和结果归属。
- 把搜索、Entry 读取和 Source 证据读取定义成受服务端范围控制的工具。
- 让每条最终引用对应服务端实际读取并核验过的原文证据。
- 支持幂等提交、单会话串行、取消、失败恢复和逐阶段可观测性。
- 保留旧 Reader API 与回答转候选链路，供 Web 在迁移前继续使用。

**Non-Goals:**

- 不实现连续追问、指代解析、工作集复用或把整段对话自动塞入模型上下文。
- 不实现模型规划器、反复搜索、自主调查循环、多 Agent 或联网搜索。
- 不实现知识增删改、目录操作、回答保存工具或绕过候选确认的写入。
- 不实现 Web/App 正式界面、推送、离线、SSE/WebSocket 流式输出。
- 不在本 change 删除旧 Reader 页面、旧 API 或现有 `answer-to-candidate` 能力。

## Decisions

### 1. 对话属于 Workspace 和创建者，范围只到 Workspace/项目

`KnowledgeConversation` 固定保存 `workspace_id`、`owner_user_id`、当前 `scope_type`（`workspace` / `project`）与可空 `project_id`。列表、详情、消息和 Run 都同时按当前用户与 Workspace 过滤；首版对话不在 Workspace 成员之间共享。

用户更换范围时新增一条 `scope_change` 系统消息并更新当前范围。历史消息和 Run 保留各自的范围快照，不随当前范围回写。存在活动 Run 时拒绝切换范围，避免“正在回答时范围被改写”的歧义。

目录节点不再出现在 Web 或 App 的范围选择器中。项目内工具仍可利用目录路径排序、展示归属和定位证据。

备选方案：保留节点范围，或允许每条消息任意携带范围。前者在移动端选择成本高且使用意图弱，后者会造成同一对话的范围难以理解，因此不采用。

### 2. 对话消息、Run 和执行记录分别持久化

核心数据对象如下：

- `KnowledgeConversation`：对话身份、所有者、当前范围、标题与最后活动时间。
- `KnowledgeMessage`：用户、助手和系统消息；保存稳定文本、消息类型、创建时间与可选 `client_message_id`。
- `KnowledgeAgentRun`：一次用户消息对应的一次执行，保存范围快照、状态、当前步骤、取消标记、重试信息、降级摘要和错误。
- `KnowledgeAgentToolCall`：每次工具调用的顺序、工具名、脱敏参数摘要、结果摘要、状态和耗时。
- `KnowledgeAgentModelInvocation`：每次 embedding、重排、回答调用的用途、prompt 版本、provider、model、fallback、错误、耗时及可获得的用量。
- `KnowledgeAgentEvidence`：本轮实际读取并允许引用的 Entry、Project、Source、Attachment、核验原文、定位信息与内容指纹快照。

用户消息和待执行 Run 在同一事务中写入。助手消息先作为占位消息绑定 Run，终态时一次性写入结构化回答和状态，避免失败时出现一半答案。原始敏感 prompt 与整份 Attachment 不进入可观测记录，只保存必要摘要和证据片段。

备选方案：只保存最终消息，或把全部运行细节塞进消息 JSON。只存结果无法恢复和排障；单 JSON 难以查询、约束与演进，因此采用分表。

### 3. 每个问题创建异步 Run，客户端通过轮询恢复

提交接口接收 `client_message_id` 和文本，在事务内创建用户消息、助手占位消息及 `waiting` Run，立即返回其标识。进程内 Worker 原子领取 Run，按 `waiting → processing → completed | partial | failed | cancelled` 转换；API 可查询 Run 当前步骤及终态回答。

同一对话最多一个 `waiting` 或 `processing` Run。为兼容 SQLite/MySQL，Run 使用可空 `active_slot`：活动态写固定值 `active`，终态置空，并以 `(conversation_id, active_slot)` 唯一约束实现单会话串行。`(conversation_id, client_message_id)` 唯一约束保证网络重试返回原消息和 Run，而不是重复执行。

Worker 领取时记录租约时间。进程重启后，超过阈值的 `processing` Run 可重新入队一次；由于工具全为只读且最终结果事务提交，重复执行不会修改正式知识。超过重试上限则失败。取消请求在步骤边界检查；无法中断的模型调用完成后丢弃结果并将 Run 标为取消。

备选方案：同步请求等待答案，或立刻引入 Celery/Redis。同步模式不适合移动网络恢复；外部队列会过早增加部署复杂度，当前进程内 Worker 足以验证产品纵向链路。

### 4. 首版采用固定、有限的只读执行图，而非开放式规划器

首版 Run 顺序固定：

1. 搜索正式知识；
2. 批量读取候选 Entry；
3. 读取并核验有限数量的 Source/Attachment 证据；
4. 组织回答；
5. 服务端校验引用并提交终态。

每一步有固定次数和结果上限，复用现有混合召回，回答上下文最多使用 15 条 Entry。项目范围可加入该项目的 Project Context；Workspace 范围不会把所有项目 Context 拼接到 prompt，而是在结果中保留项目名供区分。

每个新问题独立执行，不把历史对话作为事实依据；历史仅用于展示和恢复。后续连续追问 change 再引入追问判定、显式工作集和有上限的研究循环。

备选方案：首版就让模型自由选择工具和循环次数。这样难以界定成本、取消、证据完备性与失败恢复，也会让“连续追问”和“首次问答”无法分别验收，因此不采用。

### 5. 工具范围由服务端注入，并受“已发现对象集合”约束

内部工具契约分为：

- `search_confirmed_knowledge(query)`：在 Run 固化的 Workspace/项目范围检索正式 Entry，返回 Entry 句柄、摘要、项目与目录归属。
- `read_entries(entry_ids)`：只读取本轮搜索结果或用户显式引用、且仍属于 Run 范围的 Entry 完整内容。
- `read_source_evidence(entry_id, source_ids)`：只读取已发现 Entry 的真实关联 Source/Attachment，并生成可核验 Evidence。

`workspace_id`、`project_id` 和用户身份来自 Run 与服务端会话，不出现在模型可控制参数中。所有对象读取都重新校验 Workspace、项目范围和 Entry—Source 关系；模型猜出的 UUID 即使存在也不能读取。

备选方案：仅依赖 ORM 查询前的 Workspace 过滤，或让模型传完整查询条件。两者都容易在新增工具时产生越权缺口，因此额外维护本轮已发现集合并集中实施工具授权。

### 6. 引用先生成 Evidence，再由模型选择句柄

读取 Source 时使用现有证据归一化能力，在 Attachment 的 `text_content` 或 `ocr_text` 中定位原文，保存数据库中的精确子串，而不是保存模型改写文本。Evidence 同时记录 Entry/Source/Attachment 关系、项目和标题快照、可用定位信息、内容指纹与本轮用途。

回答模型只接收不透明 Evidence 句柄和已核验原文，并返回句柄列表。服务端最终校验句柄属于本 Run、仍符合范围且状态为可引用；模型自由生成的 ID 或 quote 不进入响应。无法核验的来源可以记录为不可用工具结果，但不能成为引用。关键结论无有效 Evidence 时，回答必须标记为部分完成或知识不足。

历史回答保留生成时的 Evidence 快照；来源后来变化或删除时，不静默重写历史回答，客户端可依据内容指纹显示“来源已变化/不可用”。

备选方案：继续只校验模型输出的 `entry_id/source_id`，或只保存 Entry 内容片段。前者不能证明 quote 真实存在，后者无法追溯原始 Source，均不满足可信阅读目标。

### 7. 降级按阶段记录，最终 Run 汇总而不掩盖局部失败

混合检索服务需要把 embedding 与重排阶段的 provider/model/fallback/error 元数据返回给 Run，而不是只返回排序结果。回答阶段沿用 `AIProvider`，每次调用都写 `KnowledgeAgentModelInvocation`。工具调用也保存成功、空结果、部分失败或错误状态。

Run 的 `fallback_summary` 聚合各阶段结果，API 同时提供可面向用户的简化状态和可排障的阶段记录。确定性召回可作为显式降级继续执行；回答模型不可用时，Run 不伪装成正常 AI 回答，而是返回可识别的 `partial` 或 `failed` 结果。

备选方案：只沿用最终响应的单个 `is_fallback`。它无法表达“embedding 失败但重排成功”或“检索正常但回答失败”，因此不采用。

### 8. 新 API 与旧 Reader 并存一个迁移周期

新增 `/api/knowledge-agent` 下的对话、消息、范围和 Run API。旧 `/api/projects/{project_id}/reader/ask` 及回答转候选接口保留，现有 Web Reader 不在本 change 迁移；旧端点可在代码和文档中标记兼容态，但不能偷偷代理到尚未完成的连续对话协议。

后续 Web 接入 change 将 AI 阅读入口并入统一对话并移除节点范围；移动端接入 change 直接消费新 API。待两端迁移和人工验收完成后，再单独移除旧 Reader。

备选方案：本次直接替换旧端点和页面。这样会把底座、客户端交互和兼容清理绑成一个大 change，难以独立验证，也会放大回滚风险。

## Risks / Trade-offs

- [进程内 Worker 在多实例下重复领取] → 使用数据库原子状态更新、租约和幂等终态提交；上线多实例前增加针对 MySQL 的并发测试。
- [Evidence 原文归一化无法匹配 OCR 噪声] → 复用现有模糊定位取得真实子串；匹配失败时禁止引用并显式记录不可用，不降低验证阈值来制造“可信”引用。
- [Run 表与观测表增长较快] → 列表接口游标分页，工具结果只存摘要；保留策略和归档清理由后续运维 change 决定。
- [固定执行图自主性有限] → 明确把它作为可信首次问答底座；连续追问与受限研究循环在可观测数据稳定后增量实现。
- [Workspace 范围检索噪声增加] → 保留项目名/目录路径作为排序与展示线索，并限制上下文；不以重新暴露节点选择器解决检索质量问题。
- [旧 Reader 与新 Agent 暂时行为不一致] → 旧接口保持兼容但不作为新产品契约；后续客户端 change 明确迁移和删除顺序。
- [来源后来变化导致历史证据陈旧] → Evidence 保存生成时快照和内容指纹，历史回答不重写，并向客户端暴露来源状态。

## Migration Plan

1. 新增数据库表、索引和约束；迁移只增加结构，不改写现有 Reader 数据。
2. 实现对话/消息/Run 仓储、可信范围校验、只读工具与 Evidence 生成，并用单元测试覆盖 Workspace/项目越权。
3. 调整混合检索与模型调用返回逐阶段可观测元数据，保持现有调用方兼容。
4. 实现 Worker、恢复/取消和新 API；默认按明确配置启动 Worker，并进行 SQLite 与 MySQL 兼容检查。
5. 以 API 完成 Workspace 问答、项目问答、幂等重试、取消、重启恢复、降级与真实引用走查。
6. 保留旧 Reader 和 Web 页面；后续客户端 change 验证完成后再迁移入口。

回滚时先停用知识 Agent Worker 与新路由，再回滚应用代码；新增表不影响旧 Reader，可暂时保留以避免丢失对话，只有确认无需恢复时才通过后续迁移删除。

## Open Questions

- 对话标题由首条问题确定性截断生成，还是在后续 UI change 中增加低优先级 AI 命名；本 change 默认采用确定性标题，不增加模型调用。
- Run、工具调用和 Evidence 的长期保留周期尚未确定；首版完整保留，并在获得实际规模数据后设计清理策略。
- 多 Workspace 切换时客户端是否显示跨 Workspace 的统一对话列表属于客户端信息架构问题；后端首版严格按当前 Workspace 返回。
