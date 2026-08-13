## Why

当前产品蓝图接近千行，代理每次实施单一功能都全文加载，会占用大量上下文并引入无关的远期设计。需要把蓝图改为“短索引 + 按任务读取的专题文档”，在不改变任何产品决策的前提下降低后续 OpenSpec 和实现任务的上下文成本。

## What Changes

- 将 `docs/产品蓝图与功能优先级.md` 替换为简短的 `docs/产品蓝图.md` 索引。
- 将现有内容按唯一归属拆分为产品定位、核心对象、整理确认、目录知识空间、Agent 与 AI、技术端侧、优先级与 change 顺序七份专题文档。
- 在索引中提供“开发内容 → 必读专题”的路由表，默认只加载当前任务相关的 1 至 2 份专题。
- 更新 README、`AGENTS.md`、OpenSpec 工件规则和 Grove UI skill，禁止无差别加载全部蓝图文件。
- 删除重复的“已锁定产品决策”全文汇总，改由索引指向各决策的唯一专题位置。

Non-Goals：

- 不修改、增删或重新解释任何已锁定产品决策。
- 不修改业务代码、数据库、API 或页面实现。
- 不修改历史归档工件中的旧路径和当时上下文。
- 不为每个 OpenSpec capability 建立一份重复的产品说明。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `project-workflow`：README 与仓库守则必须提供产品蓝图索引和按任务读取规则，使协作者无需加载全部专题即可定位权威产品上下文。
- `frontend-foundation`：Grove UI skill 必须先读取蓝图索引，再按当前页面或交互任务路由到相关专题，禁止默认全文加载所有蓝图文档。

## Impact

- 文档结构：`docs/产品蓝图.md` 与 `docs/产品蓝图/`。
- 文档入口与代理守则：`README.md`、`AGENTS.md`、`openspec/config.yaml`。
- 主规格：`project-workflow`、`frontend-foundation`。
- 前端专属规范：`.codex/skills/grove-ui-conventions/SKILL.md` 及其界面元数据。
- 现有长蓝图路径被删除，当前生效引用全部迁移到新索引；历史归档引用保持不变。
