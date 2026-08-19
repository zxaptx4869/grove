## Context

目录共创已完成“从零起草”（澄清 → 候选树 → 内联编辑 → 确认应用 → 对话调整），但入口仅限空目录，且草稿模型没有“针对某个正式节点”的概念。蓝图要求“对任意节点进行 AI 拓展”，旧项目 KnowStruct 已验证“完整目标子树 + 递归差异（新增/保留/建议移除）”的交互，用户能清楚看到 AI 将新增什么、移除什么。

现状约束：

- `directory_drafts` 每项目一份活跃草稿，状态机 `drafting / awaiting_input / pending_confirm / confirmed / discarded / failed`，`next_action` 为 `clarify / generate`；
- 现有 `apply_draft` 只允许空目录项目（从零起草），拒绝非空项目；
- `delete_node` 递归删除节点及后代，**不检查子树内是否有正式 Entry**（Entry 挂在 node_id 上，删除节点会连带删除正式记录）；
- 对话调整 `refine` 已支持“返回完整树自动替换”，轮数上限 30，不做截断压缩；
- Grove Node 无 `normalized_name` 列，名称规范化在服务层用 `strip().casefold()` 完成。

## Goals / Non-Goals

**Goals:**

- 从知识空间目录树节点菜单与内容区发起「AI 拓展」，复用共创工作区（抽屉）完成生成、差异确认与对话微调；
- Directory Agent 读取目标节点、现有子树、项目快照与相关 Entry，输出目标节点下的完整目标子树；
- 后端递归计算差异（新增 / 保留 / 建议移除），建议移除默认勾选、含正式 Entry 的子树受保护不可移除；
- 确认时单事务应用：创建新增、删除勾选移除；同时给手动删除节点增加同样的 Entry 保护；
- 每项目保持一份活跃草稿；开新拓展时提示覆盖旧草稿。

**Non-Goals:**

- 真正的“调整现有目录”（跨子树移动、目标节点或保留节点改名/改说明）留后续 change；
- 语义检索、相似知识推荐、流式输出、多草稿并行不做；
- 不改正式 Node/Entry 数据模型，不改从零起草行为。

## Decisions

### D1：数据模型 — 复用 DirectoryDraft，新增 kind 与 target_node_id

在 `directory_drafts` 增加两列：

- `kind`：`draft`（从零起草，默认）| `expand`（节点拓展），非空、服务端默认 `draft`；
- `target_node_id`：可空 FK 指向 `nodes.id`，仅 `expand` 使用。

替代方案：新建 `directory_expansion_drafts` 表。否决理由：编辑、对话、确认、worker 全部与起草共用，拆表会复制整条链路，收益仅是“概念更清晰”。

### D2：状态机 — expand 跳过澄清

`kind=expand` 时 `next_action` 直接为 `generate`，worker 的澄清分支跳过；状态流转与起草一致：

```text
drafting → pending_confirm → confirmed（应用）/ discarded（丢弃）
```

失败保留 `last_error` 可重试；对话轮数上限 30 沿用。

### D3：API 与响应

- 新增 `POST /api/projects/{id}/directory-draft/expand`，请求体 `{node_id}`：校验目标节点属于该项目 → 创建或复用活跃草稿并重置（清空节点与消息、清零轮数与澄清批次、置 `kind=expand`、`target_node_id=node_id`）→ 入队异步生成；
- `GET /directory-draft`、`PATCH /nodes`、`POST /messages`、`POST /discard` 沿用；
- `POST /apply` 按 `kind` 分支：`draft` 保持空目录校验，`expand` 走新增/移除合并；
- `DraftOut` 增加 `kind`、`target_node_id`，`expand` 草稿额外返回 `diff`（新增/保留/建议移除的递归快照），前端不再自行比对。

### D4：Agent 输入与输出

输入组装（复用 `_build_context_text` 扩展）：

1. 目标节点：祖先路径 + 名称 + 说明；
2. 现有子树：目标节点下现有子节点的名称层级与说明（深度 2–3）；
3. Project Context 快照：项目概要、当前关注、目录主题、近期主题、Entry 覆盖摘要；
4. 相关 Entry：目标节点子树全部 Entry 的标题 + 主类型 + 截断内容（每条 ≤200 字、最多 40 条，优先直接挂载与最近更新，超出标注“已截断”）。

输出为 `DirectoryDraftDraft`（嵌套 children），表示**目标节点下的完整目标子树**。Prompt 约束：

- 现有子节点按原名保留，禁止改名；确需改名时保留原名并说明需手动操作；
- 目标节点自身的名称与说明不得出现在输出中（系统固定）；
- 名称简洁、说明一句话、新增层级 ≤5、新增节点 ≤30；
- 输出始终是候选草稿，不触碰正式目录。

### D5：差异算法 — 规范化名称递归比对

在服务层对现有正式子树与草稿目标子树按 `strip().casefold()` 规范化名称递归比对：

- 两边都有 → `kept`，递归比对 children，保留节点不更新名称/说明；
- 只在草稿侧 → `added`；
- 只在现有侧 → `removed`，计算子树内 Entry 数；>0 时 `blocked=true` 并携带 `blocker_count`。

不新增 `normalized_name` 列，与现有 Entry 建议逻辑保持一致。

### D6：受保护移除 — 与手动删除共用

新增 `count_subtree_entries(db, project_id, node_ids)` 与 `assert_subtree_removable(...)`：

- AI 确认应用时：勾选的移除项必须是差异中的 `removed` 且未被阻断；任一受保护移除被勾选 → 整批回滚并返回阻断数量与路径；
- 手动删除：`delete_node` 在递归删除前做同一校验，子树含正式 Entry 返回 409 并给出阻断数量；
- 删除目标节点时，若它是活跃 `expand` 草稿的 `target_node_id`，草稿置 `discarded`，防止基于失效基准继续确认。

理由：Grove 现状删节点会连带删正式 Entry，与“正式记录可溯源”铁律冲突；AI 移除与手动删除必须行为一致，否则出现“AI 不让删、手动能删”的反差。

### D7：确认应用

`kind=expand` 的 `apply`：

1. 校验草稿为 `pending_confirm`、目标节点仍存在且属于项目；
2. 校验草稿树合法（parent 引用、无环、名称长度、新增 ≤30、新增层级 ≤5）；
3. 受保护移除校验（见 D6）；
4. 同一事务：删除勾选移除子树 → 创建勾选新增节点（根级追加到目标节点现有子节点之后，深层按草稿父子关系）→ 标记 `confirmed` → `schedule_refresh(directory_changed)`；
5. 任一失败整体回滚，草稿保持 `pending_confirm` 可修正重试。

重复提交：草稿已 `confirmed` 后 apply 返回 409，不做幂等重放。

### D8：前端交互

- `NodeTree` 节点菜单新增「AI 拓展」；`ProjectPage` 内容区（选中节点时）增加「AI 拓展」按钮；
- `DirectoryDraftDialog` 增加 `mode` 与 `targetNode`：标题“AI 拓展节点「xxx」”；打开时调用 expand 接口并轮询；
- 差异面板：`新增` 复选框默认勾选、可取消；`保留` 仅展示；`建议移除` 复选框默认勾选，受保护项禁用并显示“含 N 条正式知识，不可移除”；
- 存在受保护移除时顶部提示“含正式知识的节点无法由 AI 移除，如需改名/移动/改说明请使用手动编辑”；
- 页脚统计：`新增 N · 建议移除 M（其中 K 个受保护不可移除）`，按钮文案“应用拓展”；
- 对话区沿用双栏布局与轮询，refine 返回新目标子树后重新拉取 diff；
- 手动删除弹窗在受保护时展示阻断数量与原因。

### D9：覆盖确认（方案 A）

打开新节点的拓展时若已存在活跃草稿：前端先弹确认“将覆盖当前未应用的候选”，确认后调用 expand 接口；后端复用同一草稿并重置，不创建第二份。

### D10：产品专题同步

“建议移除默认勾选（受保护除外）”与旧蓝图“删除默认不选中”不一致，属用户基于旧项目实测拍板的产品决策；在 `docs/产品蓝图/目录与知识空间.md` 中同步更新，并在本 design 记录缘由（默认不选中导致用户误以为 AI 未响应）。

## Risks / Trade-offs

- [AI 把改名表达为“删旧+建新”，受保护时出现“新名可建、旧名删不掉”的双节点场景] → Prompt 禁止改名现有节点；差异面板对受保护移除给出明确原因；新增节点可由用户取消勾选。
- [建议移除默认勾选增加误删风险] → 差异面板用警示样式与“将删除 N 个节点”汇总；受保护校验兜底正式 Entry；删除后仍可手动重建。
- [相关 Entry 截断丢失上下文，影响生成质量] → 优先直接挂载与最近更新，超出部分标注截断；生成后可对话补充意图。
- [手动删除加入保护后用户被拒时困惑] → 删除弹窗与差异面板统一展示阻断数量与原因，引导手动调整目录或先处理 Entry。
- [覆盖活跃草稿导致未应用候选丢失] → 前端先确认再覆盖；丢弃内容仅为候选草稿，不触碰正式目录。

## Migration Plan

- Alembic 新增迁移：`directory_drafts.kind`（String(16) 非空默认 `draft`）、`directory_drafts.target_node_id`（BigInt 可空 FK → nodes.id）；
- 回滚：撤销迁移删除两列；业务代码与规格同步回退。
