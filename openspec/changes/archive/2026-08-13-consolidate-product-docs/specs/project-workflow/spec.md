## ADDED Requirements

### Requirement: README 文档入口可寻址
仓库根目录 MUST 包含 `README.md`，其中 SHALL 登记当前产品蓝图、`AGENTS.md`、OpenSpec 主规格与活动变更目录的路径和用途，并 SHALL 说明仓库目录结构与常用开发、验证命令。

#### Scenario: 新协作者找到权威文档入口
- **WHEN** 新协作者阅读仓库根目录的 `README.md`
- **THEN** 能定位当前产品蓝图、代理工作守则、OpenSpec 主规格和活动变更目录

#### Scenario: 新协作者找到开发与验证命令
- **WHEN** 新协作者准备启动或验证项目
- **THEN** 能从 `README.md` 找到前后端启动命令、质量检查命令和 OpenSpec 工作流说明

## REMOVED Requirements

### Requirement: 文档路由可寻址
**Reason**: 独立路由文档与 README 重复且已包含过时入口，README 将承担唯一文档导航职责。

**Migration**: 将产品蓝图、代理守则、OpenSpec 主规格和活动变更入口迁移至根目录 `README.md`，删除 `docs/项目上下文与文档路由.md`。
