## MODIFIED Requirements

### Requirement: README 文档入口可寻址
仓库根目录 MUST 包含 `README.md`，其中 SHALL 登记产品蓝图索引、`AGENTS.md`、OpenSpec 主规格与活动变更目录的路径和用途，并 SHALL 说明仓库目录结构与常用开发、验证命令。产品蓝图索引 MUST 提供任务到专题文档的路由，协作者 SHALL 先读索引，再只读取当前任务相关的专题。

#### Scenario: 新协作者找到权威文档入口
- **WHEN** 新协作者阅读仓库根目录的 `README.md`
- **THEN** 能定位产品蓝图索引、代理工作守则、OpenSpec 主规格和活动变更目录

#### Scenario: 协作者按任务加载产品上下文
- **WHEN** 协作者准备规划或实施一个具体 change
- **THEN** 能从产品蓝图索引定位并只读取当前任务相关的 1 至 2 份专题，而无需加载全部产品文档

#### Scenario: 新协作者找到开发与验证命令
- **WHEN** 新协作者准备启动或验证项目
- **THEN** 能从 `README.md` 找到前后端启动命令、质量检查命令和 OpenSpec 工作流说明

## ADDED Requirements

### Requirement: 产品蓝图采用渐进式文档结构
仓库 MUST 使用 `docs/产品蓝图.md` 作为唯一产品路由入口，并 SHALL 将详细产品决策放在 `docs/产品蓝图/` 的专题文档中。索引 MUST 保持简短、提供阅读规则和任务路由；同一产品决策不得在多个专题中重复维护。

#### Scenario: 产品决策按需读取
- **WHEN** 代理处理只涉及一个业务领域的任务
- **THEN** 默认上下文包含产品蓝图索引和对应专题，不包含无关的全部专题

#### Scenario: 产品决策保持单一来源
- **WHEN** 一个产品决策发生变化
- **THEN** 只需更新其权威专题及必要的路由链接，不需要同步多份决策正文
