## ADDED Requirements

### Requirement: 产品原型作为版本化设计参考
仓库 MUST 在 `docs/prototypes/` 保存可直接访问的 Grove 产品原型及说明文档。说明文档 SHALL 记录原型版本、覆盖页面、运行方式和权威边界，并 SHALL 明确原型中的静态数据与模拟交互不代表正式功能已经实现。

#### Scenario: 协作者访问当前产品原型
- **WHEN** 协作者从 README 进入产品原型
- **THEN** 能打开版本化 HTML、了解覆盖页面，并确认当前实现状态仍以 OpenSpec 主规格和正式代码为准

#### Scenario: 后续 change 引用原型
- **WHEN** 一个 OpenSpec change 实施原型覆盖的前端页面或交互
- **THEN** 其设计按需引用对应原型页面并记录有意偏离项，不要求读取或实现无关页面

#### Scenario: 正式前端采用原型设计
- **WHEN** 协作者将原型中的页面落地到正式前端
- **THEN** 使用现有 React、Tailwind、shadcn/ui 和 Lucide 实现，不直接复制原型的内联样式、演示脚本或静态业务状态

#### Scenario: 关键页面视觉验收
- **WHEN** 一个 change 完成原型所覆盖的关键桌面页面
- **THEN** 在该 change 范围内使用 1280px、1440px 和 1600px 视口与原型对照，并对有意差异保留可追溯说明
