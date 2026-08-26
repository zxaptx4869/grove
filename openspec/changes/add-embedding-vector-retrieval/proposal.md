## Why

当前重复/相似判断与语义检索采用「确定性召回（关键词/字符重叠）+ LLM 重排」：同义替换、生活化问法没有字面重叠时会漏召回，LLM 看不到候选；关系判断的 duplicate/new 依赖 LLM 判定，存在不稳定。优化清单 A1 + A3 的方向是引入 embedding 向量召回 + 相似度阈值规则接管大部分重复判断，LLM 只处理模糊区间。火山方舟现主推向量模型 `doubao-embedding-vision`（基础版与 large 已下线），已确认可用。

## What Changes

- 新增 embedding 能力：`AIProviderSettings` 增加 embedding Provider/模型配置（复用豆包密钥），提供 embedding 编码服务（方舟 `/embeddings/multimodal` 端点，纯文本输入）与连接测试。
- 新增 Entry 向量持久化表与异步重建：Entry 创建、编辑、删除、版本恢复、修订应用后触发向量重建，复用现有 Worker 模式；向量按 Workspace/Project 隔离存储。
- 混合召回（hybrid）：语义搜索、相似知识推荐、Reader 证据召回、候选关系判断统一改为「确定性召回 + embedding 召回」合并去重；embedding 未配置或调用失败时降级为纯确定性召回并显式标记，禁止静默降级。
- 关系判断阈值规则：相似度高于上限 → 规则直判 `duplicate`（不调 LLM）；低于下限 → 规则直判 `new`（不调 LLM）；中间区间才交给 LLM 判定 `duplicate` / `supplement` / `conflict`；`supplement` 与 `conflict` 始终保留 LLM。
- 模型设置页新增「语义模型（Embedding）」卡片：复用豆包密钥、模型名可改、测试连接、停用（回退确定性链路）。
- 可观测性：embedding 路径记录 provider / model / is_fallback / error，与现有文本/视觉模型一致。

## Capabilities

### New Capabilities
- `embedding-retrieval`：embedding 配置与编码、Entry 向量持久化与异步重建、混合召回、相似度阈值规则。

### Modified Capabilities
- `semantic-search`：候选召回由「关键词与字符重叠确定性召回」改为「确定性 + embedding 混合召回」，未配置或失败时降级确定性。
- `similar-entry-recommendation`：候选召回改为混合召回，降级语义不变。
- `entry-relation-suggestions`：相似 Entry 检索改为混合召回；新增相似度阈值规则，高区间直判 `duplicate`、低区间直判 `new`。
- `reader-qa`：证据召回复用语义检索的混合召回，保留未配置时降级确定性。
- `ai-provider`：模型配置范围从文本/视觉扩展到 embedding；连接测试增加 embedding；embedding 密钥复用豆包视觉密钥。

## Non-Goals

- 不引入向量数据库或 ANN 索引（继续 BLOB + 应用层暴力余弦）。
- 不做多模态检索 / 文搜图 / 图搜图（`doubao-embedding-vision` 本次仅按纯文本使用）。
- 不做稀疏向量检索（250615 起的稀疏向量输出留作后续优化项）。
- 不改变关键词搜索（`search`）的现有行为。
- 不跨 Workspace 检索、不改变 Entry 项目归属。
- 不自动写入或覆盖正式记录：规则直判的 `duplicate` / `new` 仍是建议，最终动作由用户确认。
- 不建立正式标注集；阈值用现有历史判定小样本粗标 + 行为信号持续校准。
- 不改动 Reader 引用校验、冲突展示等既有语义。

## Impact

- 后端：新增 embedding 服务、Entry 向量表、向量重建 Worker、embedding 配置 API；修改 `semantic_search` / `entry_relation` / `reader` 召回与关系判定；Alembic 新增迁移（`ai_provider_settings` 加字段、新增 `entry_embeddings` 表）。
- 前端：模型设置页新增「语义模型（Embedding）」卡片。
- 依赖：不新增第三方包（复用 httpx 调方舟 REST 端点），如接入官方 SDK 则在 design 中评估。
- 可观测性：embedding 调用与重建链路记录 provider / model / fallback / error，失败告警并降级。
