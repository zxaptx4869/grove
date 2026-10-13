## Why

知识对话目前只能新建与切换：标题由首条消息自动截取，用户既改不了名字，也没法把误建、问废的对话从列表里清掉，Web 会话轨道与移动端对话历史会持续堆积（Web 每次在空列表刷新还会自动建一条）。对话仍是当前主要工作面（移动端「待处理 / 知识」两栏尚未实现），先补齐最基本的会话生命周期管理。

## What Changes

- 新增重命名端点 `PATCH /api/knowledge-agent/conversations/{conversation_id}`：提交标题（去除首尾空白、非空、长度 ≤255），返回更新后的对话摘要；用户命名后 MUST 不再被首条消息的自动命名覆盖。
- 新增删除端点 `DELETE /api/knowledge-agent/conversations/{conversation_id}`：按**软删**语义写 `deleted_at`，消息、Run、工作集版本、草稿与调查记录全部保留、不做物理删除与级联清理；已删除对话的列表、详情、消息、Run、草稿等所有读写路径一律按不存在处理（404），列表不再返回。
- 对话存在 `waiting` / `processing` Run 时删除 MUST 返回 409，与范围切换口径一致；重复删除同一对话 MUST 幂等返回成功，不因重试或双击报错。
- 将此前未写入规格的「标题自动生成」显式化：仅当对话从未被用户命名且标题仍为默认值时，才用首条消息前 30 字（超出加省略号）自动命名。
- Web 会话轨道每行提供重命名与删除入口，删除前二次确认并说明「对话将从列表移除、内容保留」；删除后自动创建并选中一条新对话。
- 移动端对话历史 Sheet 每行提供重命名与删除入口，删除后回到空白新对话（不在服务端提前创建，符合「首次发送时才创建 Conversation」的既有原生行为）；读取到已被其他端删除的对话时按不存在处理并回到空白新对话。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `knowledge-agent-conversation`：新增「对话重命名与用户命名优先」「对话软删与读路径隐藏」两项需求，覆盖命名校验与自动命名边界、活动 Run 冲突、幂等删除、删除后 404 与列表隐藏。
- `native-knowledge-agent-conversation`：新增「原生对话重命名与删除」需求，覆盖历史列表行操作、重命名弹层、删除确认、删除后回空白新对话与已删对话的 404 恢复。

## Non-Goals

- 不做物理删除、不做彻底清理与数据导出（产品蓝图中「数据导入、导出与彻底删除」仍未启动）。
- 不做回收站 / 已归档列表 / 恢复入口：软删记录只从列表隐藏，恢复留待后续有明确需求时再定。
- 不做批量删除、空对话自动清理、对话列表分页与搜索。
- 不改动 AI 编排、模型调用、预算与题目无关的移动端页面（收集箱、来源详情、待处理 / 知识栏目保持现状）。

## Impact

- 后端：`backend/app/models/knowledge_agent.py` 新增 `deleted_at` 与 `title_source` 列；`backend/app/services/knowledge_agent/conversations.py` 增加重命名 / 软删服务并收口读取过滤；`get_owned_run`、`get_owned_draft` 增加所属对话未删除校验；`backend/app/api/knowledge_agent.py` 增加两个端点；新增一个 Alembic 迁移；扩展 `backend/tests/test_knowledge_agent_conversations.py` 等回归测试。
- Web：`frontend/src/pages/KnowledgeAgentPage.tsx`（会话轨道行操作、确认弹层、删除后新建）、`frontend/src/lib/api.ts` 与页面测试。
- 移动端：`mobile/src/knowledge-agent/components/HistorySheet.tsx`、`ConversationScreen.tsx`、`hooks/useConversationController.ts`、`api.ts`、`queryKeys.ts` 与对应测试。
- 工程：迁移需手动执行 `cd backend && .venv/bin/alembic upgrade head`（`--reload` 不会应用迁移）；开发库 SQLite 未启用外键级联，本次软删不依赖级联行为。
- 不影响：正式 Entry / Candidate 数据（`candidates` 不引用对话）、AI 可观测性、Workspace 隔离与来源追溯边界。实施完成、自动化验证与用户真机走查通过前不归档、不推送、不合并。
