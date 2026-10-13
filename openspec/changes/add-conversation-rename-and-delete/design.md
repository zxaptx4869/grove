## Context

对话当前只有创建、列出、读取与范围切换；标题在首条消息时由服务端自动截取（`backend/app/services/knowledge_agent/runs.py:342`、`candidate.py:607`、`entry_revision.py:541` 三处同口径判断），用户无法改名，也没有任何删除或隐藏手段。Web 会话轨道列出当前用户全部对话（`frontend/src/pages/KnowledgeAgentPage.tsx:513`），并在列表为空时自动创建一条（同文件 `:377`）；移动端对话历史 Sheet 每行只支持切换（`mobile/src/knowledge-agent/components/HistorySheet.tsx`），其空白新对话状态由客户端维护、首次发送才创建服务端 Conversation（`mobile/src/knowledge-agent/hooks/useConversationController.ts:391`）。

约束：按 Workspace + owner 隔离，越权一律 404；开发库 SQLite 未启用 `PRAGMA foreign_keys`（`backend/app/db/session.py:53`），数据库级联在开发库不生效；产品要求对话内容不做物理清除，正式 Candidate / Entry 不受对话生命周期影响（`backend/app/models/extraction.py:64` 只引用 Extraction 与 Source）。

## Goals / Non-Goals

**Goals:**

- 用户可重命名自己的对话，且命名结果不会被自动命名覆盖。
- 用户可把对话从列表移除，实现方式为软删：数据保留、所有读路径按不存在处理。
- Web 与移动端提供一致的重命名与删除入口，删除后都落到「新建」状态。

**Non-Goals:**

- 不做物理删除、恢复入口、回收站、批量删除、空对话自动清理、对话列表分页与搜索。
- 不改变对话范围、消息、Run、工作集、候选草稿与修订草稿的既有行为，也不调整 AI 编排与预算。

## Decisions

1. **软删用 `deleted_at` 单列，不引入状态枚举。** 对话没有多态生命周期需求，单列即可表达「已删除」；未来若加恢复，只需清空该列。备选 `status` 枚举（同项目归档）被否：项目有进行中/暂停/已完成/已归档四态筛选需求，对话没有，引入枚举只会扩大状态机与迁移面。
2. **读取过滤集中收口在服务层四个加载器**：`list_conversations`、`get_owned_conversation`、`get_owned_run`、`get_owned_draft`（后两者在 `backend/app/api/knowledge_agent.py:438` 与 `:659` 的直读端点使用，不经对话校验）。备选是逐端点补校验，被否：对话相关端点有 20 余个，逐点加会漏，且新增端点容易再次漏。集中后新增端点默认继承语义。
3. **活动 Run 期间删除返回 409**（用户决定），复用范围切换的冲突口径（`conversations.py` 的 `change_scope`）。副作用是删除与后台 Worker 不产生竞态：`waiting`/`processing` 存在时删除被拒，Worker 领取到的 Run 其对话必然未被删除（`backend/app/knowledge_agent_worker.py:97`）。备选「删除即取消」被否：会在用户无预期时丢弃正在进行的一次问答。
4. **命名归属用 `title_source`（`auto` / `user`）而非布尔锁标记。** 自动命名三处入口的判定从「标题仍是默认值」改为「`title_source = auto` 且标题仍是默认值」，这样用户把标题改回默认值后也不会被覆盖。布尔 `title_locked` 被否：语义只表达「锁」，将来若要加 AI 建议标题或用户清空命名，需要再加列。
5. **重命名只更新 `updated_at`（由 `onupdate` 自动写），不动 `last_activity_at`**（用户决定）。列表排序语义保持为「最近一次问答活动」，避免纯改名把对话顶到列表最前；代价是重命名后排序不刷新，需在验收时确认这符合预期。
6. **删除后落点两端都是「新建」，但机制不同**：移动端回空白新对话（`startNewConversation`，不创建服务端记录，符合既有「首次发送才创建」规格）；Web 没有草稿态，直接调用创建接口建一条并选中。备选「两端都选中列表下一条」被否：用户明确要落到新建；备选「Web 也做草稿态」被否：会扩大 Web 侧改动面，与本次范围不相称。
7. **API 形态**：`PATCH /api/knowledge-agent/conversations/{id}` 提交 `{"title": ...}` 并返回 `KnowledgeConversationOut`（客户端可就地更新该行，避免重拉整表）；`DELETE /api/knowledge-agent/conversations/{id}` 返回 HTTP 200 与 `{"ok": true}`，与既有删除接口一致（`backend/app/api/sources.py:590`、`backend/app/api/projects.py:223`）。重复删除幂等返回成功，避免双击与弱网重试报错；备选 204 No Content 被否：两端 `request` 封装都要新增空响应体分支，收益不抵改动。
8. **标题自动生成行为显式写入规格。** 该行为此前只存在于代码里，本次改名逻辑依赖它，因此一并固化口径（前 30 字符 + 省略号、只在未命名时生效），避免下次改动时被误删。
9. **迁移一次加两列**：`deleted_at`（可空时间戳）与 `title_source`（`server_default='auto'`）。回滚为 drop 两列，软删标记消失即恢复可见，无数据丢失风险。落地后必须手动执行 `cd backend && .venv/bin/alembic upgrade head`。
10. **移动端已删对话按不存在处理**：对话查询错误分类为 `not_found` 时回到空白新对话并失效历史列表，其余错误分支（网络、鉴权）保持现状。
11. **会话行操作入口按端侧习惯收敛，避免常驻按钮噪声**（用户走查后调整）：Web 每行的「⋯」菜单仅在该行悬浮、聚焦或菜单展开时显示；原生端取消行内常驻按钮，改为长按该行弹出操作小窗，并额外提供读屏自定义操作 `重命名`/`删除`，列表保持干净。两端的输入校验、二次确认与 409/404 处理完全一致。

## Risks / Trade-offs

- [读取过滤漏改一处，已删除对话仍可被读取或写入] → 过滤集中在四个加载器；回归测试逐条覆盖列表、详情、消息、范围切换、Run 直读、可观测性、草稿直读与取消请求。
- [软删数据长期累积，占用与审计口径无人清理] → 本次明确不清理；彻底删除与导出留给产品蓝图未启动的「数据导入、导出与彻底删除」。
- [移动端本地持久化的未完成工作仍引用已删对话，重启后尝试恢复已删对象] → 删除成功后必须清理本地 pending / recovery 状态；写入走查清单，由用户真机确认恢复行为。
- [Web 删除后自动新建与「空列表自动创建」两条路径叠加，出现多余空对话] → 删除流程内直接创建并选中，不经过 refresh 的空列表分支；测试覆盖删除最后一条对话的场景。
- [重命名不改最近活动时间，用户可能疑惑列表顺序未变] → 属有意决策，验收时一并确认。
- [标题校验口径在两端与服务端三处重复] → 服务端为唯一权威（拒绝非法输入），客户端只做同样的前置校验用于即时提示。

## Migration Plan

1. 新增一个 Alembic revision：`knowledge_conversations` 加 `deleted_at`（DateTime(timezone=True), nullable）与 `title_source`（String(16), nullable=False, server_default='auto'）。
2. 开发库执行 `cd backend && .venv/bin/alembic upgrade head`（`--reload` 不会应用迁移），随后重启后端并 `curl` 验证两个新端点返回 401 而非 404。
3. 生产部署前确认 MySQL 8 支持 `ALTER TABLE ... ADD COLUMN`（两列均可空/带默认值，属在线 DDL 快速路径）；本次不涉及数据回填。
4. 回滚策略：drop 两列即可回到本次改动前状态；软删期间被隐藏的对话会在回滚后重新可见。

## Open Questions

无。软删语义、活动 Run 冲突、命名标记、删除后落点、排序口径与 API 返回形态均已确认；真机交互、视觉与读屏验收由用户在走查阶段执行。
