## Why

Grove 已完成「整理」（提取、确认、归档）与「检索」（关键词、语义搜索），但整理完成后的「使用知识」环节还缺一块：用户不能基于已确认知识提问，并获得带证据的回答。P1 的差异化能力之一是 Reader Agent 带引用问答，它直接支撑「整理完成后回来查找、阅读或使用知识」这一 MVP 成功指标。

## What Changes

- 项目层新增「AI 阅读」视图（`?view=ai-read`），支持两种问答范围：节点阅读（当前节点及其子树）与项目阅读（整个项目）。
- 复用语义检索（确定性召回 + 语义重排）召回 top-15 已确认 Entry 作为 Reader 上下文；项目级问答叠加 Project Context 快照。
- 新增 Reader Agent：输出带引用的结构化回答，关键结论附 Entry 与 Source 引用（含原文片段）；知识不足时明确说明、不调用模型自身知识；检测到矛盾 Entry 时并列展示冲突。
- 引用在应用层校验（`entry_id` / `source_id` 必须真实且属于当前问答范围），防止幻觉引用。
- 回答即时展示、不是正式知识；用户「保存为知识」时先弹编辑框（可改标题与内容），确认后创建「AI 阅读问答」虚拟 Source，并把回答转为 Candidate 进入确认台，保证可溯源。
- 接口按消息化设计（question / answer 消息结构、scope 显式传参），为后续多轮对话预留扩展点；本次只实现单轮问答。

## Capabilities

### New Capabilities
- `reader-qa`：节点与项目范围的带引用问答，含知识不足与冲突可见。
- `answer-to-candidate`：把 AI 阅读回答保存为 Candidate 的确认流程，通过虚拟 Source 保持可溯源。

### Modified Capabilities
（无）

## Non-Goals

- 不做外部知识 / 联网搜索（P3）、不做跨项目问答、不做 Discovery Agent 与知识图谱。
- 不做多轮对话（本次单轮，但接口与前端按消息化设计预留扩展）。
- 不自动写入正式 Entry——回答必须经用户确认转 Candidate 后归档。
- 不改造现有语义检索、关键词搜索、目录共创与关系判断的行为。
- 不做回答内容的流式输出（本次同步返回）。

## Impact

- 后端：新增 Reader Agent（`agents/reader.py`）、问答服务（`services/reader.py`）、回答转 Candidate 服务与「AI 阅读问答」虚拟 Source 创建；新增问答与保存接口与 schema；复用 `semantic_search_entries`、Project Context 公共接口、Candidate / Source / Attachment 模型。
- 前端：`ProjectPage` 新增「AI 阅读」视图（`?view=ai-read`）、消息列表容器（第一版渲染 1 问 1 答）、引用展示与跳转、知识不足 / 冲突提示、「保存为知识」编辑框；`lib/api.ts` 新增接口与类型。
- 数据库：虚拟 Source 复用现有 Source / Attachment 模型，本次无新表（对话历史表留待多轮阶段）。
- 可观测性：Reader 生成记录 `provider` / `model` / `is_fallback` / `error`，模型失败时降级为确定性结果并标记原因，禁止静默降级。
