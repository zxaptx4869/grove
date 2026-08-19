# add-semantic-retrieval 任务清单

## 1. 骨架搭建（共享召回与语义重排）

- [ ] 1.1 抽取 `services/similarity.py`：字符归一化、bigram、Jaccard 重叠与 `retrieve_similar_entries`，从 `entry_relation.py` 抽出且行为保持不变
- [ ] 1.2 改造 `services/entry_relation.py` 复用共享召回工具；运行 `cd backend && .venv/bin/pytest tests/test_entry_relation.py` 确认无回归
- [ ] 1.3 新建 `agents/semantic.py`：`SemanticRankingDraft`（`results: [{entry_id, reason}]`）与 `run_semantic_agent`，未配置密钥（`TestModel`）时兜底返回确定性排序并标记 `is_fallback`
- [ ] 1.4 新建 `schemas/semantic_search.py`：语义搜索 / 相似推荐响应模型（含 `project_name`、`reason`、`is_fallback`）

## 2. 后端核心实现

- [ ] 2.1 新建 `services/semantic_search.py`：`semantic_search_entries`（确定性召回对齐 title/content/node/source title + 语义重排 + fallback + provider/model 可观测）
- [ ] 2.2 新建 `api/semantic_search.py`：`GET /api/semantic-search?q=&project_id=`（项目内与全局，越权项目 404，Workspace 隔离）
- [ ] 2.3 在 `services/semantic_search.py` 新增 `recommend_similar_entries`（同一项目、排除自身、复用召回与重排）
- [ ] 2.4 新增 `GET /api/entries/{entry_id}/similar`（越权 Entry 404，返回同一项目相似 Entry）
- [ ] 2.5 后端测试：新建 `tests/test_semantic_search.py` 覆盖召回、重排、fallback、项目内/全局、越权、相似推荐排除自身；运行 `cd backend && .venv/bin/pytest` 通过

## 3. 前端实现

- [ ] 3.1 `lib/api.ts`：新增 semantic-search 与 similar 接口及类型（`reason`、`is_fallback`、`project_name`）
- [ ] 3.2 搜索页增加「语义搜索」显式开关与结果展示，结果可识别关键词 / 语义检索模式与降级状态
- [ ] 3.3 Entry 详情侧栏增加「相关知识」并展示推荐结果与相关理由
- [ ] 3.4 前端构建与测试：`cd frontend && npm run build`、`npm run test:run`、`npm run lint` 通过

## 4. 验证与收尾

- [ ] 4.1 静态检查：`cd backend && .venv/bin/ruff check .` 通过
- [ ] 4.2 规格校验：`openspec validate --all --strict` 通过
- [ ] 4.3 手工走查：项目内 / 全局语义搜索、Entry 详情相似推荐、未配置密钥时的降级提示
- [ ] 4.4 全绿后执行 `openspec archive add-semantic-retrieval` 同步主规格，本地提交（不推送、不合并）
