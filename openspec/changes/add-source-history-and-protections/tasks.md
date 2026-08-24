## 1. 后端

- [ ] 1.1 `api/sources.py`：`GET /api/sources` 支持可选 `limit`；新增 `GET /api/sources/query`（筛选/搜索/分页）
- [ ] 1.2 `schemas/source.py`：`SourceOut` 增加 `project_locked`、`evidence_entry_count`；新增 `SourcePageOut`
- [ ] 1.3 `api/sources.py`：改归属保护（confirmed 候选或证据 → 409）；删除保护（唯一证据 → 409）
- [ ] 1.4 列表/查询批量组装新字段（一次 IN 分组，避免 N+1）

## 2. 后端测试

- [ ] 2.1 `tests/test_sources.py`：limit 生效；query 筛选/搜索/分页/total；改归属 409；删除唯一证据 409；删除多证据成功

## 3. 前端

- [ ] 3.1 `InboxPage`：右侧最近 10 条 + 右上角「查看全部来源」按钮（与 tabs 同高）
- [ ] 3.2 新增 `SourceHistoryPage`（`/sources`）：项目/状态/未归属筛选、搜索、分页、行内操作
- [ ] 3.3 `SourceList`：`project_locked` 禁用改归属；删除确认（evidence_entry_count>0 提示影响条数）
- [ ] 3.4 `AppShell` 移除「采集与来源」；`App.tsx` 注册 `/sources`；`ProjectPage` 首页来源入口（预筛跳转）

## 4. 前端测试

- [ ] 4.1 `InboxPage.test.tsx`：最近来源请求带 limit、查看全部来源按钮
- [ ] 4.2 新增 `SourceHistoryPage` 测试：筛选/搜索/分页/操作
- [ ] 4.3 `SourceList` 测试：禁用改归属、删除确认

## 5. 全量验证与收尾

- [ ] 5.1 后端 `pytest` + `ruff`、前端 `test:run` + `build` + lint 通过
- [ ] 5.2 `openspec validate --all --strict` 通过后归档并同步主规格
- [ ] 5.3 本地提交（不 push、不 merge）
