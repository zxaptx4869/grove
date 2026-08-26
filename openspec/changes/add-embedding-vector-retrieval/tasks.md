## 1. 骨架与数据模型

- [x] 1.1 `AIProviderSettings` 增加 `embedding_provider` / `embedding_model` / `embedding_key_tail` / `embedding_available` 字段（默认 `doubao` / `doubao-embedding-vision-251215` / NULL / false）
- [x] 1.2 新增 `EntryEmbedding` 模型：`workspace_id` / `project_id` / `entry_id` / `model` / `dimension` / `embedding BLOB` / `status`（ready/pending/failed）/ `error` / 时间戳，`UNIQUE(entry_id, model)`，并在 `models/__init__.py` 导出
- [x] 1.3 生成 Alembic 迁移（`ai_provider_settings` 加字段 + 新建 `entry_embeddings` 表），并执行 `cd backend && .venv/bin/alembic upgrade head` 验证

## 2. embedding 编码服务与配置

- [x] 2.1 新增 `services/embedding.py`：`encode_text` 调方舟 `POST {doubao_base_url}/embeddings/multimodal`（`input: [{type:"text", text}]`），返回 `(向量, provider, model, is_fallback, error)`
- [x] 2.2 实现离线确定性 demo embedding（字符 bigram 哈希到固定维度并归一化），未配置密钥或调用失败时返回并标记降级
- [x] 2.3 `get_embedding_model` 读取 `AIProviderSettings.embedding_model`，密钥复用豆包视觉密钥（同一 provider 的 secret）
- [x] 2.4 `test_embedding_connection` 用最小纯文本编码验证并更新 `embedding_available`
- [x] 2.5 扩展 AI 设置 schema 与 API：`GET /api/settings/ai` 返回 embedding 脱敏配置；`PUT /api/settings/ai/embedding` 只接收模型名；`POST /api/settings/ai/embedding/test`；`DELETE /api/settings/ai/embedding` 停用

## 3. 向量持久化与异步重建

- [x] 3.1 新增 `services/vector_store.py`：向量 upsert / 删除 / 按 Workspace+Project 查询、BLOB 序列化（struct float32）、余弦相似度计算
- [x] 3.2 新增 `embedding_worker.py`：轮询 `status != ready` 记录批量编码，失败写 error 并退避重试，幂等覆盖写；启动时扫描历史 Entry 全量补齐
- [x] 3.3 Entry 创建/编辑/删除/版本恢复/修订应用路径标记向量 `pending` 或级联删除（`services/entry.py` 相关函数）
- [x] 3.4 在 `main.py` 注册 embedding Worker 启停（复用现有后台任务模式，测试环境可关闭）

## 4. 混合召回与阈值规则集成

- [x] 4.1 新增 `services/vector_search.py`：确定性召回 ∪ embedding 召回（仅 ready 向量）→ RRF 融合排序，embedding 不可用时降级纯确定性并日志告警
- [x] 4.2 语义搜索 `semantic_search_entries` 与相似推荐 `recommend_similar_entries` 改用混合召回
- [x] 4.3 Reader 证据召回改用混合召回（`reader.py`）
- [x] 4.4 关系判断 `entry_relation.py` 改用混合召回，并实现阈值规则：top-1 相似度 ≥ `T_high` 直判 `duplicate`、≤ `T_low` 直判 `new`、中间区间交 LLM；`supplement`/`conflict` 始终走 LLM
- [x] 4.5 阈值常量集中配置（初值 `T_high=0.85` / `T_low=0.45`），复用 `_apply_recommendation` 的目标校验与降级逻辑

## 5. API 与前端

- [x] 5.1 前端 `lib/api.ts` 增加 embedding 配置的 fetch / save / test / clear 方法，`queryKeys` 增加对应键
- [x] 5.2 模型设置页新增「语义模型（Embedding）」卡片：状态徽标、模型名可改、测试连接、停用、说明复用视觉密钥；不展示密钥输入框
- [x] 5.3 新卡片接入现有 `useGroveMutation` 与 toast 反馈，错误与降级状态可见

## 6. 阈值标定

- [x] 6.1 写一次性标定脚本：用现有 107 条候选的历史关系判定（duplicate/new/supplement）与对应 top-1 相似度分布，输出 T_high / T_low 建议值
- [x] 6.2 按标定结果确认或调整默认阈值常量，并把结论记录到 change 的 design.md Open Questions

## 7. 测试与验证

- [x] 7.1 后端测试：embedding 编码（真实/降级）、向量存储与隔离、混合召回降级、阈值规则直判与非法目标降级、配置 API 脱敏与连接测试
- [x] 7.2 更新既有语义搜索 / 相似推荐 / 关系判断 / Reader / AI 设置测试，适配新字段与混合召回（离线 demo embedding 下行为保持确定性）
- [x] 7.3 运行验证：`cd backend && .venv/bin/ruff check app tests` 与 `cd backend && .venv/bin/pytest` 全绿
- [x] 7.4 运行 `openspec validate --all --strict` 通过；按 AGENTS.md 完成本地提交（不推送、不合并）
