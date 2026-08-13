## Why

仓库当前同时使用 `README.md`、`PROPOSAL.md` 与 `docs/项目上下文与文档路由.md` 作为入口，且早期提案中的装修模板、PydanticAI 阶段和路线判断已与产品蓝图冲突，后续实现代理容易读取错误基线。现在需要将产品与技术决策收敛到明确的单一入口，并让 OpenSpec 主规格与新的文档结构保持一致。

## What Changes

- 将 `PROPOSAL.md` 中仍有效的技术选型、AI 架构原则和开放技术决策合并到产品蓝图。
- 将 `README.md` 更新为仓库唯一文档入口，直接索引产品蓝图、代理守则、主规格与活动变更。
- **BREAKING** 删除过时的 `PROPOSAL.md` 与重复的 `docs/项目上下文与文档路由.md`。
- 更新 `AGENTS.md` 与 `openspec/config.yaml`，统一指向产品蓝图和对应 change 设计文档。
- 修改 `project-workflow` 主规格：不再要求专门的文档路由文件，改为要求 README 提供完整且可寻址的文档入口。
- 保留已归档 change 和历史任务书中的旧路径引用，作为当时决策记录，不追溯改写历史。

### Non-Goals

- 不修改业务代码、API、数据库或前端页面。
- 不改变当前产品蓝图中的功能范围和优先级。
- 不创建产品功能 change，不实施蓝图第 18 节中的任何业务能力。
- 不清理已归档 OpenSpec 工件中的历史引用。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `project-workflow`: 将文档入口从专门的路由文档迁移到根目录 README，并要求 README 能定位当前产品蓝图、代理守则、OpenSpec 主规格和活动变更。

## Impact

- 文档：`docs/产品蓝图与功能优先级.md`、`README.md`、`AGENTS.md`、`openspec/config.yaml`。
- 删除：`PROPOSAL.md`、`docs/项目上下文与文档路由.md`。
- 规格：`openspec/specs/project-workflow/spec.md` 经 delta spec 同步更新。
- 不影响运行时行为、依赖、API、数据库迁移和部署。
