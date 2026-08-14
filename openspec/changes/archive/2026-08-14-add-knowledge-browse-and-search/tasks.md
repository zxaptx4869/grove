## 1. 后端 Entry 响应与范围读取

- [x] 1.1 `backend/app/schemas/entry.py`：`EntryEvidenceOut` 增加 `source_title`，`EntryOut` 增加 `node_name`
- [x] 1.2 `backend/app/services/entry.py`：`entry_out` 解析 `node_name` 与每条证据 `source_title`；`list_entries_by_node` 增加 `scope` 参数（`direct`/`descendants`）与后代递归，统一按 `created_at DESC`
- [x] 1.3 `backend/app/api/entry.py`：列表接口接受 `scope` 查询参数；读取时预加载 `Entry.node` 与 `Entry.evidences → EntrySourceEvidence.source`

## 2. 后端搜索

- [x] 2.1 `backend/app/services/search.py`：关键词搜索（`title`/`content`/`Node.name`/`Node.description`/`Source.title`），`LIKE` 大小写不敏感、转义 `%`/`_`/`\`，用 `EXISTS` 命中来源标题
- [x] 2.2 `backend/app/schemas/search.py` 与 `backend/app/api/search.py`：`SearchEntryOut`（`EntryOut` + `project_name`）与 `GET /api/search?q=&project_id=`
- [x] 2.3 `backend/app/main.py`：注册 search 路由

## 3. 前端 API 与查询键

- [x] 3.1 `frontend/src/lib/api.ts`：`fetchNodeEntries` 增加 `scope`；新增 `searchEntries`；`EntryPayload`/`EntryEvidencePayload` 补 `node_name`/`source_title` 类型
- [x] 3.2 `frontend/src/lib/queryKeys.ts`：`nodeEntries` 键带 `scope`；新增 `search` 键

## 4. 前端知识空间浏览

- [x] 4.1 抽取可复用 `EntryCard` 与 `EntryList` 组件（卡片突出内容与来源，列表突出标题/目录/类型/来源/更新时间）
- [x] 4.2 `ProjectPage` 增加卡片/列表切换（`localStorage` 按项目记忆）与「仅本节点/仅后代」切换
- [x] 4.3 `ProjectPage` 内容区顶部加项目内搜索框（防抖约 300ms），搜索时隐藏范围切换、保留视图切换

## 5. 前端全局搜索

- [x] 5.1 `AppShell` 把「搜索」由禁用项改为 `NavLink` 指向 `/search`
- [x] 5.2 `SearchPage` 实现关键词输入、结果卡片/列表、所属项目名与点击跳转 `/projects/{id}?view=directory`

## 6. 测试与验证

- [x] 6.1 后端测试：直接/后代范围、`source_title`/`node_name`、搜索四字段命中、通配符转义、Workspace 隔离
- [x] 6.2 前端测试：视图偏好记忆、范围切换、项目内搜索、全局搜索跳转
- [x] 6.3 运行 `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`
- [x] 6.4 运行 `cd frontend && npm test -- --run && npm run lint && npm run build`
- [x] 6.5 运行 `openspec validate --all --strict`
