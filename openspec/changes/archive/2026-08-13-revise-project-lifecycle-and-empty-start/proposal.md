## Why

蓝图「产品基线修正」第一项（项目说明、生命周期、默认空目录、归档与恢复、移除装修模板默认路径、小屏电脑提示）已经在 `rebuild-product-foundation-experience` 中实现到代码。但该 change 归档时，主规格 `openspec/specs/project-management/spec.md` 没有同步两条 `MODIFIED` 需求，仍保留「创建时 MUST 选择 decoration/empty 模板并生成 149 节点」的旧行为。当前代码与产品蓝图已一致，唯独主规格落后，形成「蓝图 / 主规格 / 代码」三者不一致，会误导后续 change 的验收与范围判断。

## What Changes

- 修正 `project-management` 主规格中的「创建项目并选择目录模板」需求：改为新项目默认状态为进行中、目录为空，系统 MUST NOT 要求或展示装修模板选择。
- 补充「多项目归属与列表」需求：项目列表 MUST 支持按进行中、暂停、已完成、已归档四种状态筛选，已归档项目默认不出现在非归档列表。
- 明确历史客户端仍以 `decoration` 参数调用时仅作兼容处理，正式前端不展示该入口。
- 本 change 仅同步主规格，不修改业务代码；代码现状已与蓝图一致。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `project-management`: 修正「创建项目并选择目录模板」与「多项目归属与列表」两条需求，使主规格与蓝图、代码一致。

## Impact

- `openspec/specs/project-management/spec.md` 被更新。
- 业务代码无需变更；`Project.template`、模板解析与种子代码、`backend/app/templates/decoration_knowledge_tree.md` 按既有设计保留为历史兼容。
- 无 API、依赖或数据库变更。

## Non-Goals

- 不删除遗留 `template` 字段、`decoration_knowledge_tree.md` 或模板解析/种子代码（历史兼容，遵循 `rebuild-product-foundation-experience` 既有决策）。
- 不新增 Source、Attachment 等 P0-A 后续能力，不进入蓝图建议顺序的第 2 项 change。
- 不修改 `node-tree`、`product-shell`、`frontend-foundation` 等其他能力规格。
