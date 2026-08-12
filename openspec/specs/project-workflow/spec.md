# project-workflow Specification

## Purpose
TBD - created by archiving change setup-project-foundation. Update Purpose after archive.
## Requirements
### Requirement: 仓库提供代理工作守则
仓库根目录 MUST 包含 `AGENTS.md`，其中 SHALL 写明三条产品铁律：AI 输出永远是候选、正式记录必须可溯源、数据按 Workspace 隔离；并 SHALL 说明 OpenSpec 工作流顺序（提案 → 规格 → 设计 → 任务 → 实施 → validate → sync specs → archive → commit）。

#### Scenario: 守则内容完整可读
- **WHEN** 读取仓库根目录的 `AGENTS.md`
- **THEN** 文件中包含「AI 输出永远是候选」「正式记录必须可溯源」「数据按 Workspace 隔离」三条铁律，以及 OpenSpec 工作流说明

### Requirement: OpenSpec 工作流骨架可用
仓库 MUST 包含 `openspec/config.yaml`，配置 schema 为 `spec-driven`，并 SHALL 提供项目上下文与工件规则。执行 `openspec validate --all --strict` SHALL 全部通过。

#### Scenario: 无活动变更时校验通过
- **WHEN** 在仓库根目录执行 `openspec validate --all --strict`
- **THEN** 命令成功退出且输出无错误

### Requirement: 文档路由可寻址
仓库 MUST 包含 `docs/项目上下文与文档路由.md`，其中 SHALL 登记 PROPOSAL.md、AGENTS.md、openspec/ 等主要文档的路径与用途，并 SHALL 说明目录结构。

#### Scenario: 新协作者找到文档入口
- **WHEN** 新协作者阅读 `docs/项目上下文与文档路由.md`
- **THEN** 能从文档路由表中定位产品提案、工作守则与 OpenSpec 变更目录

