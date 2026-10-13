## 1. 后端数据模型与迁移

- [x] 1.1 `KnowledgeConversation` 增加 `deleted_at`（DateTime(timezone=True)，可空）与 `title_source`（String(16)，非空，`server_default='auto'`），并新增一个 Alembic revision。验收：`cd backend && .venv/bin/alembic upgrade head` 可重复执行无副作用（`--reload` 不会应用迁移，改完必须手动执行）。
- [x] 1.2 确认新列不进入 API 输出（`KnowledgeConversationOut` 保持现有字段），避免客户端依赖内部状态。

## 2. 后端重命名

- [x] 2.1 `backend/app/services/knowledge_agent/conversations.py` 增加重命名服务：去除首尾空白、非空、长度 ≤255，写入标题并置 `title_source='user'`，只更新 `updated_at`（不改 `last_activity_at`、不改范围与工作集）。验收：本组测试覆盖合法标题、空白标题、超长标题、活动 Run 期间重命名。
- [x] 2.2 `backend/app/api/knowledge_agent.py` 增加 `PATCH /conversations/{conversation_id}`：复用 `get_owned_conversation`（越权、其他用户、已删除一律 404），返回更新后的 `KnowledgeConversationOut`。
- [x] 2.3 三处自动命名入口改为读 `title_source`：`backend/app/services/knowledge_agent/runs.py:342`、`candidate.py:607`、`entry_revision.py:541`，判定条件为「`title_source` 为 `auto` 且标题仍为默认值」。验收：既有自动命名用例保持通过，并新增「用户先把标题改回默认值也不被覆盖」用例。

## 3. 后端软删

- [x] 3.1 增加软删服务：记录 `deleted_at`；对话存在 `waiting`/`processing` Run 时返回 409 且不修改；对已删除对话重复调用幂等返回成功。
- [x] 3.2 读取过滤收口到四个加载器：`list_conversations`、`get_owned_conversation`、`get_owned_run`、`get_owned_draft`（后两者的直读端点在 `backend/app/api/knowledge_agent.py:438` 与 `:659`）。验收：无任何端点单独实现删除过滤，全部经由这四个加载器。
- [x] 3.3 增加 `DELETE /conversations/{conversation_id}`，返回 HTTP 200 与 `{"ok": true}`，与既有删除接口一致。
- [x] 3.4 回归测试（`backend/tests/test_knowledge_agent_conversations.py`、`test_knowledge_agent_api.py`）：删除后对话列表、详情、消息、范围切换、Run 直读、可观测性、草稿直读与取消请求均返回 404；活动 Run 期间删除返回 409；重复删除返回成功；越权删除返回 404；删除后已确认的 Candidate 与 Entry 仍存在且来源可追溯。
- [x] 3.5 `tests/test_knowledge_agent_api.py` 的未认证路由清单补两个新端点，断言未登录返回 401 而非 404。

## 4. Web 会话轨道

- [x] 4.1 `frontend/src/lib/api.ts` 增加重命名与删除调用；`frontend/src/pages/KnowledgeAgentPage.tsx` 会话轨道行增加 DropdownMenu（重命名 / 删除）与重命名 Dialog（提交前校验去空白后非空、≤255）。
- [x] 4.2 删除走二次确认 Dialog，文案说明「对话将从列表移除、内容保留」；确认期间禁用重复提交。
- [x] 4.3 删除当前对话后调用创建接口新建一条并选中（不经过 `refresh` 的空列表自动创建分支，避免出现多条空对话）；删除非当前对话只从列表移除该行。
- [x] 4.4 冲突与异常处理：409 提示需等待完成或取消；404（已被其他端删除）从列表移除并选中下一条或新建。
- [x] 4.5 `frontend/src/pages/KnowledgeAgentPage.test.tsx` 增加用例：重命名就地更新标题、首条消息不覆盖已命名标题、删除后列表移除并落到新建、409 提示、删除最后一条对话不产生多余空对话。

## 5. 原生移动端

- [x] 5.1 `mobile/src/knowledge-agent/api.ts` 增加重命名与删除调用，保持现有 `request` / `withToken` 封装与错误分类（`not_found`、`conflict`）。
- [x] 5.2 `mobile/src/knowledge-agent/components/HistorySheet.tsx` 每行增加可读屏识别的重命名与删除入口（不破坏现有切换操作），`ConversationScreen.tsx` 通过 `HistoryControl` 传入回调。
- [x] 5.3 重命名弹层（复用 `Sheet`）就地校验并就地更新该行标题，保留列表滚动位置；非法输入不发请求。
- [x] 5.4 删除确认说明「从列表移除、内容保留」，确认期间显示进行中且不可重复提交；删除非当前对话只移除该行。
- [x] 5.5 删除当前对话后调用 `startNewConversation()` 回到空白新对话，并清理 `DialogueSessionProvider` 中引用该 `conversationId` 的本地 pending / recovery 持久化状态。
- [x] 5.6 对话查询返回 `not_found` 时按不存在处理：回到空白新对话并失效历史列表，不反复重试；网络与鉴权分支保持现状。
- [x] 5.7 测试：`HistorySheet.test.tsx`、`useConversationController.test.tsx`、`ConversationScreen.test.tsx` 补用例覆盖行操作、重命名成功与非法输入、删除确认、删除当前对话回空白态与本地状态清理、409 与 404 分支。

- [x] 5.8 （复核阶段缺陷修复）对话 404 回落加守卫：本地存在未发送输入、pending 提交或待恢复 Run 时不得静默清理，保留恢复错误与重试/退出入口；仅无可恢复工作时才回空白新对话。验收：`useConversationController.test.tsx` 新增两条用例，移动端全量用例通过。

## 6. 验证、走查与交付

- [x] 6.1 共享验证命令：`cd backend && .venv/bin/pytest -q`、`cd backend && .venv/bin/ruff check .`、`cd frontend && npm run typecheck && npm run lint && npm run test:run`、`cd mobile && npm run typecheck && npm run lint && npm test`。测试尾部出现 `A worker process has failed to exit gracefully` 属既有 `useSourceLibrary` 测试隔离问题，非本次回归。
- [x] 6.2 `openspec validate --all --strict` 在实施前与收尾各执行一次并记录结果。
- [x] 6.3 本地后端冒烟（`cd backend && .venv/bin/alembic upgrade head && .venv/bin/uvicorn app.main:app --reload`）：创建对话 → 重命名返回新标题 → 首条消息不覆盖 → 删除成功 → 列表不含该对话 → 详情与消息 404 → 重复删除成功 → 活动 Run 期间删除 409；未认证访问两个新端点为 401 而非 404。
- [ ] 6.4 提供 Web 与原生端走查清单交用户验收：Web 轨道行操作与确认弹层、删除后新建；原生端历史列表行操作、弹层、删除后空白新对话、本地恢复状态清理、读屏播报与安全区。手动验收结论由用户给出，AI 不代下结论。
- [x] 6.5 每完成一段可验证修改（模型与迁移、后端接口、Web、移动端）即做本地阶段提交；推送、合并与归档须用户明确批准。
- [ ] 6.6 归档前置检查：主规格按需求标题逐条比对，全文精确搜索需要改写的既有措辞，注意场景标题不可改名；`openspec archive` 只有在实施、自动化验证与用户真机走查全部通过后才执行。
