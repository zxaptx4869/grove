# design: add-semantic-retrieval

## Context

Grove 当前只有关键词搜索（`services/search.py`，`ilike` 子串匹配），只能命中字面相同的词；当用户用不同说法表达同一含义时（如「地漏返味」与「下水道防臭」）无法召回。P1 需要补上「语义搜索和相似知识推荐」。

现有可复用资产：

- `services/entry_relation.py` 已有确定性召回 `retrieve_similar_entries`（字符 bigram + Jaccard 重叠 + 标题相等/包含），服务于候选归档时的关系判断；
- `services/ai_models.py` 提供 `get_text_model`，未配置密钥时回退离线 `TestModel`；
- 关键词搜索的 `entry_eager_options` / `entry_out` 可直接复用。

约束：AI 输出永远是候选；正式记录可溯源；Workspace 隔离；人在环上；AI 可观测（禁止静默降级）。技术栈 SQLite 开发 / MySQL 8 生产，AI Provider 只有文本（deepseek）+ 视觉（doubao），无 embedding 抽象、无向量依赖。

## Goals / Non-Goals

**Goals:**

- 在关键词搜索之上，新增按语义找知识的能力（自然语言查询、同义替换可命中）。
- 新增 Entry 详情侧栏的相似知识推荐。
- 复用现有 AI 文本模型抽象，不引入第三方依赖、不新增数据库表。

**Non-Goals:**

- 不引入 embedding / 向量库 / ANN 检索（本次明确排除）。
- 不做搜索结果问答、组合筛选、标签、批量管理、跨 Workspace、外部知识。
- 不改造已归档 `entry-relation-suggestions` 的关系判定语义。
- 相似推荐不做跨项目（跨项目发现由全局语义搜索承担）。

## Decisions

### 决策 1：采用「确定性召回 + LLM 语义重排」，不引入向量

语义检索分两段：先用确定性算法召回候选集（缩小范围），再用文本模型做语义重排（排序 + 相关理由）。

- **为何不选 embedding 向量检索**：现有 provider 无 embedding、DeepSeek 无 embedding API、MySQL 8 无原生向量类型；上向量需要新增 embedding 抽象 + 向量存储 + 向量更新/重建 + 可观测一整条链路，属于大基建，不应在验证价值前引入。
- **为何选 LLM 重排**：复用现有 `get_text_model`，无新依赖；装修/旅行领域大量知识是「专业术语 + 生活化表达并存、字面有部分重叠」，确定性召回能覆盖多数场景，LLM 负责精排与解释。
- **备选方案（作为后续 change 的候选）**：豆包 `doubao-embedding-text`（走方舟 OpenAI 兼容端点）+ MySQL 8 用 BLOB 存向量、应用层暴力余弦。待标注集验证召回缺口后再单独评估。

### 决策 2：抽取可复用的确定性召回工具层，不改关系判断行为

现有 `entry_relation.py` 的 bigram/Jaccard 召回与语义检索的召回同构。抽出一个共享工具（如 `services/similarity.py`），提供字符归一化、bigram、Jaccard 重叠、`retrieve_similar_entries` 等函数。

- 语义检索与关系判断共用该工具，但 **entry_relation 的调用结果保持不变**，避免回归。
- 语义检索的召回字段对齐关键词搜索：Entry 标题、核心内容、目录节点名称与说明、来源标题。

### 决策 3：新建语义重排 Agent，输出排序与相关理由

新建 `agents/semantic.py`，用 PydanticAI 定义结构化输出：

```text
SemanticRankingDraft:
  results: [{ entry_id, reason }]   # 按相关度从高到低
```

- 复用 `get_text_model`；当模型为 `TestModel`（未配置密钥）时，返回确定性召回的排序结果，`reason` 置空并标记 `is_fallback=True`。
- 记录 provider / model / fallback（类似 `GenerationMeta`），供可观测性使用，满足 AGENTS.md 禁止静默降级的要求。

### 决策 4：候选集与结果上限、文本截断

- 确定性召回候选集上限 20，语义重排后返回 top-10。
- Entry 文本截断：标题全量 + 核心内容前 300 字，控制每轮 LLM 的 token 与延迟。
- 个人知识库量级下该上限足够；上限与截断作为常量集中配置，便于后续调参。

### 决策 5：语义搜索 UI = 同一搜索框 + 显式开关

语义搜索作为现有关键词搜索的显式增强入口，不新开独立搜索页：

- 搜索框增加「语义搜索」开关，用户显式选择后走语义检索；
- 结果可识别检索模式（关键词 / 语义），避免静默兜底导致不可预期。

否决「低命中自动转语义」：静默、不可预期，违背可解释与可观测原则。

### 决策 6：相似推荐的位置与范围

- 位置：Entry 详情侧栏「相关知识」。
- 范围：仅该 Entry 所属项目（排除自身）。
- 跨项目发现由全局语义搜索承担，相似推荐不做跨项目。

### 决策 7：无新增依赖、无数据库变更

语义检索实时计算，不持久化向量或候选，因此无 Alembic 迁移、无新表。可观测性通过结构化返回字段与日志表达，不为此新增落库。

## Risks / Trade-offs

- **[召回天花板] 同义替换 / 无语面重叠会被确定性召回漏掉，LLM 看不到就重排不了** → 用真实数据集人工标注集量化 `Recall@10`，对比关键词基线；若明显不达标，再开 change 引入向量。
- **[成本与延迟] 每次语义检索触发一次 LLM 重排** → 候选集上限 20 + 文本截断；语义搜索为显式触发，不做自动重排。
- **[静默降级] 未配置密钥时悄悄返回确定性结果** → 返回结构显式携带 `is_fallback`，日志告警，前端可识别。
- **[过度联想] LLM 可能把「语义近但实际无关」判为相关** → 返回相关理由供用户判断，限制 top-K，AI 输出仍是候选、不写入正式记录。
- **[复用回归] 抽取召回工具可能影响关系判断** → 只抽取不改行为，保留 `entry_relation` 既有测试，新增工具层单测。

## Migration Plan

- 无数据迁移：本次不新增数据库表、不改现有模型，仅新增服务 / Agent / API / 前端组件。
- 部署与回滚：新增端点向后兼容，前端开关默认关闭（关键词搜索行为不变）；回滚只需移除新端点与开关。

## Open Questions

- 语义检索的验证标注集由谁、在哪个阶段产出：本次 change 内产出小规模标注集（装修场景），还是留待验证阶段另行准备？
- 未配置密钥时的 fallback 排序规则：按召回分数降序，还是维持创建时间倒序（与关键词搜索一致）？
