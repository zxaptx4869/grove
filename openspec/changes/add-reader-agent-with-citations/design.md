# design: add-reader-agent-with-citations

## Context

Grove 已完成「整理」与「检索」能力：关键词搜索、语义搜索 / 相似推荐、Project Context Snapshot、确认台与 Candidate / Entry 归档链路都已就绪。前端与后端目前**没有任何 AI 阅读实现**，本次是从零到一新增 Reader Agent。

可复用资产：

- `services/semantic_search.py`：`_recall_by_query`（确定性召回）与 `agents/semantic.py` 的 `run_semantic_agent`（语义重排 + 可观测降级）；
- `services/entry.py` 的节点子树查询与 `entry_out`；
- Project Context 公共接口（`ProjectContextOut`）与 `entries_summary`；
- Candidate / Source / Attachment 模型与确认台（review）流程。

约束：AI 输出永远是候选；正式记录必须可溯源到 Source；Workspace 隔离；人在环上；AI 可观测（禁止静默降级）。

## Goals / Non-Goals

**Goals:**

- 在节点或项目范围内，基于已确认 Entry 提供带引用的回答。
- 知识不足与冲突可见；引用经应用层校验，防止幻觉。
- 回答可保存为 Candidate（虚拟 Source 保证可溯源），不直接写 Entry。
- 接口与前端按消息化设计，为后续多轮对话预留扩展点。

**Non-Goals:**

- 不做多轮对话（本次单轮）、不做流式输出。
- 不做外部知识 / 联网搜索、跨项目问答、Discovery Agent、知识图谱。
- 不改造现有语义检索、关键词搜索、目录共创与关系判断行为。

## Decisions

### 决策 1：先做单轮问答，接口按消息化设计预留多轮

本次实现单轮问答，但接口、响应与前端都按「消息」结构设计：

```text
POST /api/projects/{id}/reader/ask
  { message, scope: "project" | "node", node_id? }
  → { answer, citations, insufficient, conflicts, provider, model, is_fallback, error }
```

- `message` 是一条用户消息，`answer` 是一条助手消息，scope 每轮显式传入；
- 前端用消息列表容器渲染（第一版只有 1 问 1 答）。

理由：从单轮到多轮的增量是「会话持久化 + 历史注入 + 前端追加消息」，核心的检索、引用校验、转 Candidate 逻辑全部保留；消息化设计让演进只加层、不重写。备选（现在直接做多轮）被否决：多轮还需要对话表、历史截断与指代理解，属于未验证价值前就背聊天系统成本。

### 决策 2：复用语义检索做证据召回

Reader 的证据召回复用语义检索的底层能力：

```text
加载问答范围 Entry（节点子树或项目）
  → _recall_by_query(问题) 召回 top-20
  → run_semantic_agent 重排 top-15
  → 组装 Reader 上下文（标题 + 内容截断 300 字 + 来源标题）
```

- 项目级问答：加载项目内全部已确认 Entry，并叠加 Project Context 快照（概要 / 目录主题 / 近期主题）到 Reader 上下文；
- 节点级问答：加载节点及其子树的已确认 Entry，不叠加项目上下文快照，但附节点路径与说明。
- `run_semantic_agent` 自带 fallback：未配置密钥或模型失败时返回确定性排序并标记，Reader 据此继续生成或降级。

### 决策 3：Reader Agent 结构化输出与引用校验

新建 `agents/reader.py`，用 PydanticAI 定义结构化输出：

```text
ReaderAnswerDraft
├── answer: str
├── citations: [{ entry_id, source_id, quote }]
├── insufficient: bool
├── insufficient_note: str | None
└── conflicts: [{ entry_id_a, entry_id_b, summary }]
```

- 应用层对 `citations` 做校验：entry / source 必须属于当前问答范围，非法引用直接丢弃；
- 知识不足：模型必须明说；应用层兜底——`citations` 为空且模型声明不足时标记 `insufficient`；
- 冲突：只并列展示，不替用户裁决；
- 生成来源与降级原因（`provider` / `model` / `is_fallback` / `error`）随响应返回，满足可观测铁律。

### 决策 4：回答转 Candidate——「AI 阅读问答」虚拟 Source

保存回答时创建虚拟 Source，保证溯源链完整：

```text
用户点「保存为知识」→ 编辑框（可改标题/内容）
  → 创建虚拟 Source（归属当前项目；title="AI 阅读问答：{问题}"；text attachment=回答全文）
  → 创建待采纳 Candidate（归属虚拟 Source；
       evidence_refs = 被引用 Entry 的原始 Source 证据 attachment_id + 原文片段）
  → 进入确认台，走既有归档流程
```

- 溯源链：Candidate → 虚拟 Source（承载问答上下文）→ 原始 Source 证据（引用原文）；
- 保存请求中的引用经服务端校验（entry / source 属于当前 Workspace 与项目），非法引用拒绝（400）；
- MVP 用 title 前缀「AI 阅读问答：」标识虚拟 Source，不新增 Source 类型字段；若后续需要区分采集来源，再单独加 `kind`。

### 决策 5：保存前编辑，且不直接写 Entry

保存回答必须先经过编辑框确认，用户可修改标题与内容；保存只创建 Source 与 Candidate，绝不创建或修改正式 Entry——正式归档仍由确认台流程完成。

### 决策 6：无新表、无新依赖

本次虚拟 Source 与 Candidate 复用现有模型，不新增数据表；不引入第三方依赖；可观测性沿用 `is_fallback` / `error` 返回结构。

## Risks / Trade-offs

- **[引用幻觉] 模型可能引用范围外或不存在的 Entry / Source** → 应用层逐条校验并丢弃非法引用，测试覆盖。
- **[知识不足误判] 模型可能用自身知识悄悄补全** → system prompt 强约束 + `insufficient` 兜底标记 + 前端明确提示。
- **[上下文预算] 15 条 Entry 的 token 占用** → 标题全量 + 内容截断 300 字；上限与截断作为常量集中配置。
- **[模型失败] 语义重排或 Reader 生成失败** → 复用降级机制，返回确定性结果并标记原因，不 500。
- **[虚拟 Source 污染收集箱] 自动创建的来源混入用户采集列表** → title 前缀「AI 阅读问答：」标识；后续可加类型字段区分。
- **[多轮演进] 单轮设计可能不完全满足多轮** → 已用消息化接口与消息列表容器预留，演进只加历史层。

## Migration Plan

- 无数据迁移：本次不新增表、不改现有模型，仅新增 Agent / 服务 / API / 前端视图。
- 部署与回滚：新增端点向后兼容，AI 阅读视图默认隐藏入口；回滚只需移除新端点与入口。

## Open Questions

（无）
