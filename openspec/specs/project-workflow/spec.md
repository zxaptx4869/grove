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

### Requirement: README 文档入口可寻址
仓库根目录 MUST 包含 `README.md`，其中 SHALL 登记当前产品蓝图、`AGENTS.md`、OpenSpec 主规格与活动变更目录的路径和用途，并 SHALL 说明仓库目录结构与常用开发、验证命令。

#### Scenario: 新协作者找到权威文档入口
- **WHEN** 新协作者阅读仓库根目录的 `README.md`
- **THEN** 能定位当前产品蓝图、代理工作守则、OpenSpec 主规格和活动变更目录

#### Scenario: 新协作者找到开发与验证命令
- **WHEN** 新协作者准备启动或验证项目
- **THEN** 能从 `README.md` 找到前后端启动命令、质量检查命令和 OpenSpec 工作流说明
