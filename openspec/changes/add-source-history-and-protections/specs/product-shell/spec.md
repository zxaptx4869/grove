## MODIFIED Requirements

### Requirement: 项目上下文中的全局入口

应用壳侧栏 MUST 始终在顶部固定展示全局一级菜单（项目 / 收集箱 / 搜索），进入项目后一级菜单保持不变，项目上下文（项目名与项目内导航）置于其下；项目内导航 MUST 提供项目首页、知识空间、AI 阅读与确认台入口，且 MUST NOT 提供「采集与来源」入口；来源历史页 `/sources` MUST 可访问但 MUST NOT 出现在侧栏菜单中；`/projects/:id?view=sources` 旧路由 MUST 保留兼容。

#### Scenario: 一级菜单固定顶部
- **WHEN** 用户在项目列表或任意项目视图切换
- **THEN** 侧栏顶部的「项目 / 收集箱 / 搜索」保持位置不变，只有项目上下文区块随进入项目而变化

#### Scenario: 项目内不出现来源菜单
- **WHEN** 用户进入项目查看侧栏
- **THEN** 项目导航不包含「采集与来源」入口

#### Scenario: 来源历史页不进菜单
- **WHEN** 用户通过收集箱「查看全部来源」或项目首页来源入口访问 `/sources`
- **THEN** 全屏历史页正常渲染，且侧栏菜单不显示对应一级入口

#### Scenario: 旧来源路由兼容
- **WHEN** 用户直接访问 `/projects/:id?view=sources`
- **THEN** 仍可打开来源视图，不做 404
