## Why

目录从零起草（`add-directory-agent-drafting`）已完成，但已有目录只能在共创对话里让 AI 用自然语言“拆细”，没有面向正式目录节点的专门拓展入口。蓝图要求“对任意节点进行 AI 拓展”，旧项目 KnowStruct 已验证“完整目标子树 + 递归差异（新增/保留/建议移除）”的体验：用户能直观看到 AI 打算怎么改、哪些会被移除，而不是只得到一串新增节点。

## What Changes

- 知识空间目录树节点菜单与内容区新增「AI 拓展」入口，点击后打开共创工作区并针对该节点生成候选结构。
- `DirectoryDraft` 扩展 `kind`（`draft` / `expand`）与 `target_node_id`；沿用“每项目一份活跃草稿”，已存在进行中草稿时开新拓展需确认覆盖。
- 新增接口 `POST /api/projects/{id}/directory-draft/expand {node_id}`：跳过澄清，直接进入异步生成。
- Directory Agent 输入：目标节点路径/说明、现有子树、Project Context 快照与相关 Entry（目标节点子树全部，上限 40 条、每条内容截断 200 字）。
- AI 输出目标节点下的**完整目标子树**（含应保留的现有子节点）；目标节点自身与保留节点的名称/说明固定不变。
- 递归差异：`新增` / `保留` / `建议移除`；建议移除默认勾选，但子树含正式 Entry 的节点受保护、禁用勾选并显示阻断数量。
- 确认应用：单事务内创建勾选的新增节点、删除勾选的建议移除子树；任一校验失败整体回滚并保持草稿可编辑。
- 手动删除节点也增加 Entry 保护：子树含正式 Entry 时禁止删除（与 AI 移除共用同一校验），避免正式记录随节点被级联删除。
- 对话调整沿用现有 refine 语义：模型返回完整更新后的目标子树，差异面板随之刷新。
- 同步更新产品专题 `docs/产品蓝图/目录与知识空间.md`，记录“建议移除默认勾选”等与旧蓝图的差异决策。

## Capabilities

### New Capabilities
- `directory-node-expansion`：从正式目录节点发起 AI 拓展，生成完整目标子树、递归差异确认与受保护移除应用。

### Modified Capabilities
- `directory-drafting`：草稿增加 `kind`/`target_node_id`、`expand` 发起与生成、差异响应、按 kind 分流的应用逻辑。
- `node-tree`：节点删除增加“子树含正式 Entry 时禁止删除”的受保护校验。

## Non-Goals

- 真正的“调整现有目录”能力（跨子树移动、目标节点或保留节点的改名/改说明）不做，留给后续 change；AI 只表达新增与建议移除。
- 非从某节点发起的全局目录调整入口不做。
- 语义检索、相似知识推荐（`add-semantic-retrieval`）不做。
- 多节点并行草稿（每节点一份草稿）不做，保持“每项目一份活跃草稿”。
- 流式输出、消息截断与历史压缩不做，沿用现有轮询与 30 轮上限。
- 从零起草行为、正式 Node/Entry 数据模型不改。
- 完整目录差异统计与安全合并工作台不做，本次仅展示单次拓展的差异面板。

## Impact

- 后端：`agents/directory.py`（拓展生成/refine 输入）、`services/directory_draft.py`（差异计算、受保护移除、应用）、`models/directory_draft.py`（kind/target_node_id）、`api/directory_draft.py`（expand 接口）、`api/projects.py`（手动删除保护）、`schemas/directory_draft.py`（差异响应）、Alembic 迁移。
- 前端：`NodeTree.tsx`（菜单入口）、`ProjectPage.tsx`（内容区入口与抽屉接线）、`DirectoryDraftDialog.tsx`（拓展模式与差异面板）、`lib/api.ts`（新接口与类型）。
- 规格与文档：`openspec/specs/directory-drafting`、`openspec/specs/node-tree` 增量，产品专题 `docs/产品蓝图/目录与知识空间.md`。
- 无新依赖：相关 Entry 走现有节点子树查询，不引入向量检索。
