## Context

蓝图「产品基线修正」第一项要求项目默认空目录、具备生命周期与可选说明、移除装修模板默认路径、小屏只显示电脑提示。这些能力已在 `rebuild-product-foundation-experience` 中实现到代码，且该 change 已归档。

但归档后主规格 `openspec/specs/project-management/spec.md` 出现不一致：

- 「创建项目并选择目录模板」仍是旧版文字，要求创建时选择 `decoration`/`empty` 模板并生成 149 节点；
- 「多项目归属与列表」缺少按四种状态筛选的语义；
- 「项目生命周期」等 ADDED 需求已正确合并。

代码当前行为（`backend/app/api/projects.py`、`backend/app/schemas/project.py`、`frontend/src/pages/ProjectsPage.tsx`）与蓝图一致：新建项目只接受名称与可选说明，默认空目录，UI 不展示模板选择，`decoration` 仅在历史客户端显式传参时兼容。因此本 change 只需同步主规格，不动业务代码。

## Goals / Non-Goals

**Goals:**

- 使 `project-management` 主规格与蓝图、代码一致，消除「创建时必须选模板、生成 149 节点」的陈旧描述。
- 补齐项目列表按四种生命周期状态筛选的主规格约束。
- 让需求名称准确反映「默认空目录」而非「选择模板」。

**Non-Goals:**

- 不删除 `Project.template` 列、`decoration_knowledge_tree.md` 或模板解析/种子代码（保留历史兼容，遵循 `rebuild-product-foundation-experience` 既有决策）。
- 不改变任何 API 请求/响应或数据库结构。
- 不新增 Source、Attachment 等 P0-A 后续能力。

## Decisions

### D1：本 change 仅同步规格，不修改代码

代码与蓝图已经一致，问题只出在主规格合并。直接改代码属于无意义的重复实现，也会扩大变更面。因此本 change 的实现动作是「修正 delta 规格并归档同步」，业务代码保持不变。

备选：把 `decoration` 兼容路径一并删除。该路径仍被 `ProjectCreate.template` 与 `create_project` 的兼容分支引用，删除需要同时处理模型字段与 Alembic 迁移，且与 `rebuild-product-foundation-experience` 已记录的「保留历史兼容」决策冲突，故本次不做。

### D2：把需求重命名为「创建项目并默认空目录」

原需求名「创建项目并选择目录模板」在行为已改为默认空目录后不再准确，保留会造成名称与内容矛盾。使用 RENAMED 操作改名，再用 MODIFIED 更新完整内容；归档时按 RENAMED → MODIFIED 顺序应用，MODIFIED 匹配新名称。

### D3：MODIFIED 保留全部既有 Scenario

「多项目归属与列表」保留两个场景并更新状态筛选语义；「创建项目并默认空目录」保留「装修模板生成完整树」「空目录创建」两个旧场景（改述为历史兼容语义），并新增「创建空项目」「背景可选」，避免归档校验因遗漏场景而失败。

## Risks / Trade-offs

- [需求名变更导致归档匹配失败] → 先运行 `openspec validate --all --strict` 与 `openspec sync-specs`/归档校验；RENAMED 与 MODIFIED 使用同一新名称，确保匹配。
- [保留 decoration 兼容路径仍与「默认空目录」语义并存] → 在规格中明确「仅历史客户端兼容，正式前端不展示入口」，避免被误读为产品路径。
- [主规格仍有其他陈旧的 Purpose 占位] → 本次仅处理需求级不一致，Purpose 与更广的规格清理不在范围，避免扩张。

## Migration Plan

无数据库、API 或前端迁移；本 change 仅更新主规格。归档（或 sync-specs）后 `openspec/specs/project-management/spec.md` 与代码、蓝图对齐。

## Open Questions

- 后续是否要在独立 change 中彻底删除 `decoration` 兼容路径与 `Project.template` 列，待真实数据与迁移成本评估后决定。
