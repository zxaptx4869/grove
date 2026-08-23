## Context

Entry 已具备创建、编辑、移动目录与来源证据能力，但修改只更新 `updated_at`，没有版本记录；候选关系流程（`entry-relation-suggestions`）已有 `revision_draft` 与「应用修订」，但没有用户对单条 Entry 直接发起 AI 修订的路径。前端知识空间只有卡片/列表展示与「相关知识」按钮，没有编辑、版本历史或 AI 修订入口。

产品讨论已与用户确认：版本采用「保留最近 N 条」档位；AI 修订建议采用「内联一次性对话」——对话只在面板内存中，关闭即消失、不落库，每次调整携带全量对话与当前草稿；应用时结论沉淀为 Entry 新内容 + 版本记录。

## Goals / Non-Goals

**Goals:**

- Entry 创建、编辑/移动、应用修订、恢复时追加版本快照，每个 Entry 只保留最近 N 条（默认 10），支持查看与恢复。
- 知识空间卡片/列表新增「编辑」「AI 修订建议」「版本历史」三个入口（沿用「相关知识」按钮模式），不新增整条 Entry 详情弹窗。
- AI 修订建议：生成结构化草稿 → 面板内一次性对话调整 → 用户确认应用后写 Entry 并追加 `ai_revision` 版本；不进入候选确认台。
- 人工编辑 UI 补齐前端缺失的编辑表单（字段 + 目录移动，复用现有 PATCH 接口）。

**Non-Goals:**

- 不持久化修订会话与消息；不做消息表与状态机。
- 不把 AI 修订建议转为 Candidate、不新增候选类型。
- 不做批量 AI 修订建议。
- 不做逐字段 diff / 版本对比 UI；不做无限版本或审计级历史。
- 搜索页、AI 阅读、知识全景/思维导图本轮不接入编辑、修订与历史入口。
- 不实现 P2 Review。

## Decisions

### D1：版本模型与保留上限

新增 `entry_versions` 表：

```text
id、entry_id（FK entries CASCADE）、version_number（Integer）
title、content、main_type、info_nature、applicable_condition、note、node_id（快照字段）
change_type（created / edited / ai_revision / restored）
change_summary（Text，可空）
created_at
UniqueConstraint(entry_id, version_number)
```

每次变更在同一事务内追加快照，`version_number = max + 1`；超出 N（默认 10）后删除最旧版本。快照记录的是「变更后」状态（版本 N = 第 N 次变更后的状态），列表与恢复语义直观。

理由：档位二是用户确认的产品取舍；文本快照成本低，但无限历史对个人 KB 是过度设计，滚动丢弃避免膨胀。

### D2：快照时机与变更类型

- 创建 Entry（普通归档、新增节点归档、冲突并列保留）→ `created` 版本 1；
- 人工编辑字段或移动目录（`edit_entry`）→ `edited`，仅在实际字段/节点发生变化时追加，避免空版本；
- 应用候选修订草稿（`apply_revision_to_entry`）→ `ai_revision`，`change_summary` 取自候选草稿；
- 应用 AI 修订建议 → `ai_revision`，`change_summary` 取自草稿；
- 从历史恢复 → `restored`，`change_summary` 为「恢复到版本 N」；
- 补充来源证据（`add_evidence_to_entry`）→ 不产生版本。

`ApplyRevisionRequest` 增加可选 `change_summary` 字段（向后兼容），候选应用路径也记录变更说明。

### D3：版本读取与恢复 API

- `GET /api/entries/{entry_id}/versions`：返回全部保留版本，按 `version_number` 倒序，每条包含完整快照字段（含 `node_name`，实时关联目录名）。不做单独详情端点，前端从列表选择。
- `POST /api/entries/{entry_id}/restore`（body `{ version_id }`）：校验 Entry 归属当前 Workspace 且版本属于该 Entry；把字段与 `node_id` 恢复为快照，追加 `restored` 版本（无实际变化则跳过），不删除后续历史；触发项目上下文刷新。

理由：恢复是「追加新版本」而非覆盖，保证历史只增；与「修改不得破坏来源关系」一致，证据不变。

### D4：AI 修订建议 Agent 与一次性对话

新增 `agents/revision.py`：结构化输出 `RevisionReplyDraft { reply_text, draft }`，`draft` 为建议字段全集 + 修订原因 + 变更说明。系统提示约束：只基于该 Entry 内容与其来源证据，不引入外部知识；输出始终是候选草稿，不修改正式 Entry；无实质改进时 `draft` 可空并在 `reply_text` 说明。

三个端点：

- `POST /api/entries/{entry_id}/revision-suggestion`（body `{ instruction? }`）：生成草稿；
- `POST /api/entries/{entry_id}/revision-suggestion/refine`（body `{ instruction, messages, draft }`）：携带完整对话历史与当前草稿，返回更新草稿与回复；
- `POST /api/entries/{entry_id}/revision-suggestion/apply`（body 字段 + `change_summary`）：应用确认后的字段并追加 `ai_revision` 版本。

对话与草稿全部由前端持有，后端无会话表；响应携带 `provider / model / is_fallback / error`；`TestModel`（未配置密钥）或模型调用失败时降级返回、不生成草稿、记录告警日志，满足 AI 可观测性要求。

理由（为什么不走候选确认台）：确认台动作（仍按新知识创建、补充来源证据）对「修订已有 Entry」不适用，会制造重复风险；产品铁律允许「建议」作为 AI 输出容器；与 DirectoryDraft 的「内联草稿 → 用户确认 → 应用层写入」同模式。若对话中冒出值得独立保存的知识，走既有 AI 阅读「保存为知识」流程，本 change 不复制该能力。

### D5：前端入口与聚焦面板

- `EntryCard` 底部操作区与 `EntryList` 操作列新增「编辑」「AI 修订建议」「版本历史」，沿用现有「相关知识」按钮风格（图标 + 文字，列表用紧凑图标 + aria-label/tooltip）。
- 新增三个聚焦面板（不做整条 Entry 详情弹窗）：
  - `EntryEditDialog`：标题、内容、主类型、信息性质、适用条件、补充说明 + 目录选择（复用 `DirectoryTreeSelect`），保存调用现有 `updateEntry`；
  - `EntryVersionHistoryDialog`：版本列表（版本号、变更类型、变更说明、时间）→ 选中查看快照 → 「恢复此版本」带二次确认；
  - `RevisionSuggestionDialog`：对话区（消息气泡 + 指令输入）+ 当前草稿表单（可手改）+ 「应用」「放弃」；应用成功后关闭并失效相关查询。
- `ProjectPage` 为卡片/列表接入三个回调与面板状态；`api.ts`、`queryKeys` 同步扩展。

理由：按钮方案与「相关知识」一致、不引入详情弹窗；三个动作各用聚焦面板，上下文（Entry 内容）在各面板内自足。

## Risks / Trade-offs

- [恢复会把 Entry 移回旧节点] → 快照含 `node_id`，恢复即还原，属预期语义；节点删除会级联删 Entry，因此快照节点必然存在。
- [保留上限丢弃旧版本后无法恢复更早状态] → 产品确认的档位二；UI 明示「只保留最近 N 条」。
- [AI 修订建议质量依赖模型与上下文] → 仅基于该 Entry 与来源证据生成，不引入外部知识；无模型时降级可见、不生成草稿。
- [全量对话重发随轮次变长] → 个人 KB 场景可接受；面板关闭即结束，重新生成即可。
- [版本号并发冲突] → 快照在变更同一事务内 `flush` 后计算 `max + 1`，开发 SQLite / 生产 MySQL 单写场景下安全。
- [三个面板与按钮增加卡片操作区密度] → 延续「相关知识」按钮模式，桌面 1024px+ 可容纳；列表用紧凑图标收敛。

## Migration Plan

一个 Alembic 迁移：创建 `entry_versions` 表，并为既有 Entry 回填版本 1（`INSERT SELECT` 当前字段快照，`change_type='created'`，`created_at` 取 Entry 创建时间）。回滚即删表；无破坏性变更。

## Open Questions

- 保留上限 N=10 是否合适，待真实使用校准（实现中设为常量，便于调整）。
- AI 修订建议应用成功后是否提供「查看版本历史」快捷入口（体验增强，本轮可做可不做）。
