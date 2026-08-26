## Context

现状：语义搜索、相似知识推荐、Reader 证据召回、候选关系判断四条链路共用「确定性召回 + LLM 重排/判定」模式。确定性召回基于 `services/similarity.py` 的字符归一化、bigram Jaccard、标题相等/包含，以及关键词子串加成；同义替换、生活化问法无语面重叠时会漏召回，LLM 看不到候选。关系判断的 `duplicate` / `new` 由 LLM 判定，存在随机性（temperature=0 已缓解但未根治）。

真实数据量级：正式 Entry 32 条、候选 107 条（历史关系判定 new 89 / duplicate 9 / supplement 5 / pending 4），属个人知识库量级，应用层暴力余弦完全可行。

模型现状（2026-08 确认）：火山方舟向量模型中 `Doubao-embedding` 与 `Doubao-embedding-large` 已下线，主推 `doubao-embedding-vision`（对应 `doubao-embedding-vision-251215`）；纯文本输入走多模态向量化端点 `POST /api/v3/embeddings/multimodal`，请求体为 `input: [{type:"text", text:"…"}]`，稠密向量维度 2048（可降维 1024），上下文 8K。base_url 与密钥与现有豆包视觉模型一致。

约束：AI 输出永远是候选；正式记录可溯源；Workspace 隔离；人在环上；AI 可观测（禁止静默降级）。技术栈 SQLite 开发 / MySQL 8 生产，不引入向量数据库。

## Goals / Non-Goals

**Goals:**

- 提供 embedding 编码服务（方舟多模态端点、纯文本），未配置/失败时明确降级。
- 为已确认 Entry 持久化稠密向量，按 Workspace/Project 隔离，异步重建。
- 语义搜索、相似推荐、关系判断、Reader 证据召回统一升级为「确定性 + embedding」混合召回。
- 关系判断用相似度阈值规则接管高/低区间（duplicate / new），LLM 只处理模糊区间与 supplement/conflict。
- 模型设置页新增「语义模型（Embedding）」配置卡片，复用豆包密钥。
- embedding 全路径可观测：provider / model / is_fallback / error。

**Non-Goals:**

- 不引入向量数据库 / ANN 索引（BLOB + 应用层暴力余弦）。
- 不做多模态检索 / 文搜图 / 图搜图（vision 模型仅按纯文本使用）。
- 不做稀疏向量检索（250615 起支持，留作后续优化项）。
- 不改变关键词搜索（`search`）行为；不改变 Reader 引用校验与冲突展示语义。
- 不建立正式标注集；阈值用小样本粗标 + 行为信号校准。
- 不自动写入正式记录：规则直判仍是建议，用户确认后才落库。

## Decisions

### 决策 1：向量模型用 `doubao-embedding-vision-251215`

方舟当前唯一主推向量模型（base / large 已下线）。虽然定位多模态，但纯文本输入支持良好，中文 CMTEB SOTA，检索任务效果强。模型名作为 `AIProviderSettings.embedding_model` 可配置，未来换版本只需改配置并全量重建。

- 备选：OpenAI / 阿里 embedding → 需要额外供应商与密钥，与「复用豆包」的 BYOK 体系冲突，暂不选。

### 决策 2：编码走方舟多模态向量化 REST 端点，不新增官方 SDK

用 httpx 调 `POST {doubao_base_url}/embeddings/multimodal`，请求 `input: [{type: "text", text: text}]`，响应解析稠密向量。不引入 `volcenginesdkarkruntime`，保持依赖最小；抽象成 `services/embedding.py`，业务代码不接触请求细节。

未配置豆包密钥时返回离线确定性 demo embedding：对归一化文本的字符 bigram 做哈希到固定维度（如 256 维）的计数向量并归一化，保证相同输入相同输出、相近文本向量接近、不访问外部网络，供测试与降级链路使用。

### 决策 3：新增 `entry_embeddings` 表，BLOB 存向量

```text
entry_embeddings
  id, workspace_id, project_id, entry_id,
  model, dimension, embedding BLOB,
  status (ready / pending / failed), error,
  created_at, updated_at
  UNIQUE(entry_id, model)
```

- BLOB 用 struct.pack 存 float32 数组；2048 维约 8KB/条，万级量级总大小几十 MB，暴力余弦在请求内逐条计算毫秒级。
- `workspace_id` / `project_id` 冗余存储并建索引，检索时先用 SQL 过滤当前 Workspace/项目，再在应用层算余弦，隔离由数据库层保证。
- 模型变更（配置改 embedding_model）时旧模型向量标记失效，按新模型全量重建，避免混用向量空间。

### 决策 4：向量重建走独立后台 Worker，复用现有后台任务模式

参照 `context/worker.py` / `directory_worker.py` 的进程内异步循环模式，新增 `embedding_worker.py`：轮询 `status != ready` 的向量记录批量编码；失败写 `error` 并带退避重试，幂等（覆盖写）。启动时扫描历史 Entry 全量补齐。

触发点：Entry 创建、编辑、删除、版本恢复、修订草稿应用后，把该 Entry 的向量记录置为 `pending`（不存在则插入）。删除 Entry 时级联删除向量。

当前量级下也可同步编码，但选择异步：外部 HTTP 调用不进入确认/编辑主流程，失败不阻塞业务；新鲜度窗口影响有限（见风险）。

### 决策 5：混合召回共享层，并集 + RRF 融合

新增 `services/vector_search.py` 作为共享召回层，四个消费方统一走：

```text
确定性召回（现有 similarity.py，覆盖全部范围 Entry）
  ∪
embedding 召回（只覆盖 status=ready 的 Entry，cosine top-K）
  → 并集去重 → RRF 融合排序 → top-N 候选
```

- 融合用 RRF（rank-based）：`score = Σ 1/(60 + rank)`，不依赖确定性分数与 cosine 的量纲对齐，避免拍权重。
- embedding 未配置 / 失败 / 无 ready 向量时，混合召回退化为纯确定性召回，行为与现状一致；日志告警，设置页状态可见，响应契约不新增字段（LLM 重排的 is_fallback 语义不变）。
- 关键词命中加成（`_keyword_hit`）保留：确定性路径本身把精确命中排前，RRF 会保留该优势。

### 决策 6：关系判断阈值规则，LLM 只处理中间带

对候选的 top-1 相似 Entry（混合召回取相似度最高者）：

```text
cosine ≥ T_high  → 规则直判 duplicate（不调 LLM）
cosine ≤ T_low   → 规则直判 new（不调 LLM）
T_low < cosine < T_high → LLM 判定 duplicate / supplement / conflict
```

- 初值保守取 T_high=0.85、T_low=0.45（中间带放宽，宁多调 LLM 不误判），作为集中常量；实施阶段用现有 107 条候选历史判定做小样本粗标调整，上线后靠行为信号（用户接受/修改/拒绝关系建议）持续校准。
- `duplicate` 直判后仍校验 target Entry 存在且属于当前项目，非法则降级 `new`（复用现有 `_apply_recommendation` 校验）。
- `supplement` 需要识别新增内容并生成修订草稿、`conflict` 需要矛盾判断，相似度规则无法胜任，明确不接管，始终走 LLM。

小样本粗标结果（2026-08-26，排除候选自身 Entry 后 top-1 余弦分布）：

```text
duplicate : n=9  median=0.929  p25=0.880  p75=0.939  min=0.713  max=0.954
supplement: n=5  median=0.663  区间 0.638~0.693
new       : n=87 median=0.566  p25=0.488  p75=0.688  min=0.348  max=0.857
```

结论：保持 T_high=0.85（低于 supplement 下限 0.638，可规则接管多数 duplicate，漏网低相似 duplicate 交 LLM）；保持 T_low=0.45（低于所有 supplement/duplicate 样本，规则只接管明显无关的 new，零误伤风险）。上线后行为信号持续校准。

### 决策 7：embedding 配置复用豆包密钥，独立模型名

`AIProviderSettings` 新增 `embedding_provider`（默认 `doubao`）、`embedding_model`（默认 `doubao-embedding-vision-251215`）、`embedding_key_tail`、`embedding_available`。密钥复用视觉模型同一把豆包方舟密钥（同账号同 base_url），不新增密钥输入；未来切换供应商再扩展独立密钥字段。

API：

- `GET /api/settings/ai`：扩展返回 embedding 脱敏配置。
- `PUT /api/settings/ai/embedding`：只接受 `model`（模型名可选覆盖），不接收密钥。
- `POST /api/settings/ai/embedding/test`：用最小文本编码验证连接，成功更新 `embedding_available`。
- `DELETE /api/settings/ai/embedding`：停用（标记未配置，语义功能退回确定性链路）。

前端模型设置页新增第三张卡「语义模型（Embedding）」：状态徽标、模型名可改、测试连接、停用；不展示 API Key 输入框，说明「复用视觉模型密钥」。

### 决策 8：可观测性与降级

- embedding 编码返回 `(vector, provider, model, is_fallback, error)`；失败时调用方降级纯确定性召回并 `logger.warning` 告警。
- 重建 Worker 记录 provider / model / error / 重试次数，失败不静默。
- 未配置 embedding 不视为错误（产品承诺的语义检索在无 embedding 密钥时仍按现有路线工作），以日志与设置页徽标体现。

## Risks / Trade-offs

- **[阈值标定不足]** → 保守双阈值（0.85 / 0.45）放大中间带，误判交给 LLM；用现有 107 条历史判定粗标 + 行为信号校准，阈值收敛前不收紧区间。
- **[同义高相似误判 duplicate]**（如相反结论的冲突） → supplement/conflict 不规则化；规则只作用于 top-1 高相似；行为信号可回滚阈值。
- **[豆包密钥与视觉共用]**（用户清除视觉密钥则 embedding 同时停用） → 设置页徽标明确展示复用关系；停用后语义功能确定性降级，不中断。
- **[多模态端点兼容性 / 模型下线]** → 测试连接覆盖编码路径；模型名可配置，换模型只需全量重建（Worker 自动处理）；上线前在控制台确认模型非「即将下线」。
- **[新鲜度窗口]**（新 Entry 向量未就绪） → 混合召回并集保留确定性路径，新 Entry 仍可通过确定性召回进入候选，窗口影响极小；重建失败重试 + 日志告警。
- **[暴力余弦扩展性]** → 万级 Entry 内可行；若量级继续增长，再评估 ANN 或向量库，本 change 不引入。

## Migration Plan

- Alembic 迁移一：`ai_provider_settings` 新增 embedding 四字段（默认 doubao / `doubao-embedding-vision-251215` / NULL / false）。
- Alembic 迁移二：新建 `entry_embeddings` 表（含 workspace_id / project_id 索引与 entry_id+model 唯一约束）。
- 部署：迁移后启动 embedding Worker，自动扫描无向量 Entry 全量补齐（当前约 32 条，编码量可忽略）。
- 回滚：停用 embedding 配置即整体退回确定性链路；迁移回滚删除表与字段，不影响现有数据。

## Open Questions

- 是否需要把「召回模式（hybrid / deterministic）」暴露到响应供前端识别：当前设计用日志 + 设置页徽标，如验证阶段需要再补充。
