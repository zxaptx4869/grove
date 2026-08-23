## Why

Entry 已经可以编辑和移动目录，但所有修改都只留下 `updated_at`，没有任何版本记录；AI 修订建议目前只能由候选的 `supplement`/`conflict` 关系附带产生，用户无法对已有 Entry 直接发起 AI 修订并让「结论沉底」。这是 P1 的最后一个能力，需要补上基础版本历史与直接可用的 AI 修订建议。

## What Changes

- **Entry 基础版本历史（保留最近 N 条）**：
  - 创建 Entry 时建立版本 v1；
  - 每次修改（人工编辑字段或移动目录、应用候选修订草稿、应用 AI 修订建议、从历史恢复）追加一个版本快照，记录变更类型与变更说明；
  - 每个 Entry 只保留最近 N 条版本（默认 10），超出后滚动丢弃最旧版本；
  - 支持查看任一保留版本，并支持「恢复到该版本」（恢复 = 追加新版本，不删除后续历史）；
  - 来源证据的增删不产生版本。
- **AI 修订建议（内联一次性对话）**：
  - 知识空间卡片/列表新增「AI 修订建议」入口；
  - 面板内生成草稿后可继续用自然语言调整；每次「继续调整」都携带完整对话历史、当前草稿与用户新指令；
  - 对话是一次性的，关闭面板即消失、不落库；应用时把最终字段写入 Entry 并追加版本（变更类型 `ai_revision`，带变更说明与 provider/model/fallback 可观测）；
  - 不进入候选确认台，不新增候选类型，AI 永不直接写 Entry。
- **人工编辑 UI**：知识空间卡片/列表新增「编辑」入口，补齐前端缺失的 Entry 编辑表单（字段编辑 + 目录移动，复用现有 PATCH 接口）。
- **版本历史 UI**：知识空间卡片/列表新增「版本历史」入口，展示版本列表、查看快照与恢复。

## Capabilities

### New Capabilities

（无，本 change 全部落在既有 `entry` 能力上）

### Modified Capabilities

- `entry`: 新增 Entry 基础版本历史（快照、保留上限、查看与恢复）与 AI 修订建议（生成、一次性对话调整、应用并沉淀版本）需求；编辑与移动目录产生版本快照。

## Impact

- 后端：新增 `entry_versions` 表与 Alembic 迁移（含既有 Entry 回填 v1）；Entry 创建/编辑/应用修订/恢复时写快照；新增 AI 修订建议 Agent（`agents/revision.py`）与生成、继续调整、应用三个端点；新增版本列表与恢复端点；`ApplyRevisionRequest` 增加可选 `change_summary`。
- 前端：`EntryViews` 增加「编辑 / AI 修订建议 / 版本历史」按钮；新增 `EntryEditDialog`、`EntryVersionHistoryDialog`、`RevisionSuggestionDialog`；`ProjectPage` 接线；`api.ts` 与 `queryKeys` 扩展。
- 数据：新增表与回填，无破坏性变更，无回填风险（v1 取当前字段快照）。
- 依赖：无新增第三方依赖。

## Non-Goals

- 不做对话持久化、消息表与会话状态机（对话一次性、不落库）。
- 不把 AI 修订建议转为 Candidate 进入确认台；不新增候选类型。
- 不做批量 AI 修订建议。
- 不做逐字段 diff 引擎或版本对比 UI。
- 不做无限版本或审计级版本历史；只保留最近 N 条。
- 不实现 P2 Review（定期过期、冲突巡检等）。
- 搜索页、AI 阅读、知识全景/思维导图本轮不接入编辑、修订与历史入口；仅知识空间目录浏览。
- 不改变现有候选关系建议（`duplicate`/`supplement`/`conflict`）与候选 `apply-revision` 流程的既有语义。
