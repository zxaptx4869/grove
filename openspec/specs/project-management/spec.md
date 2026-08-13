# project-management Specification

## Purpose
TBD - created by archiving change add-projects. Update Purpose after archive.
## Requirements
### Requirement: 多项目归属与列表
系统 MUST 提供 `Project` 模型并归属到 Workspace；已登录用户 MUST 只能看到自己 Workspace 内的项目；跨 Workspace 的项目 MUST 不可见。

#### Scenario: 列出当前空间的项目
- **WHEN** 已登录用户请求项目列表
- **THEN** 只返回该用户 Workspace 内的项目

#### Scenario: 跨用户项目不可见
- **WHEN** 用户 B 尝试访问用户 A 的项目（通过 ID）
- **THEN** 请求失败（404），不暴露项目信息

### Requirement: 创建项目并选择目录模板
系统 MUST 支持创建项目，创建时 MUST 选择模板：`decoration`（装修模板）或 `empty`（空目录）；选择装修模板时 MUST 生成完整模板树。

#### Scenario: 装修模板生成完整树
- **WHEN** 以 `decoration` 模板创建项目
- **THEN** 项目创建成功，且其目录树包含模板中的全部节点（149 个）

#### Scenario: 空目录创建
- **WHEN** 以 `empty` 模板创建项目
- **THEN** 项目创建成功且目录树为空

### Requirement: 项目重命名与删除
系统 MUST 支持重命名项目；删除项目 MUST 在前端二次确认后执行并级联删除其全部目录节点。

#### Scenario: 重命名生效
- **WHEN** 用户重命名项目
- **THEN** 项目列表与详情返回新名称

#### Scenario: 删除项目级联清理
- **WHEN** 用户确认删除一个含目录树的项目
- **THEN** 项目及其全部节点均被删除，列表不再包含该项目

### Requirement: 项目生命周期
系统 MUST 支持进行中、暂停、已完成、已归档四种状态；状态变更 MUST 校验项目属于当前 Workspace。已归档项目可恢复到进行中，其他状态之间允许按产品界面发起明确变更。

#### Scenario: 暂停项目
- **WHEN** 用户将进行中项目变更为暂停
- **THEN** 项目状态持久化为暂停，并在进行中筛选中隐藏

#### Scenario: 归档与恢复
- **WHEN** 用户归档项目后从归档列表选择恢复
- **THEN** 项目状态变为进行中并重新出现在默认项目列表

### Requirement: 项目列表视觉结构与直接操作
项目列表 SHALL 使用真实项目 API 按进行中、暂停、已完成、已归档四种状态筛选，并按产品原型的桌面信息层级展示标题、说明、主操作、状态筛选和项目行。页面内容 SHALL 铺满应用壳剩余宽度并使用 24px 水平内边距；项目行 MUST 展示真实项目名称、可选目标与背景、目录节点数和生命周期，不得伪造正式知识数、候选数或更新时间。

#### Scenario: 桌面项目列表视觉层级
- **WHEN** 用户在 1280px、1440px 或 1600px 访问包含项目的列表
- **THEN** 标题使用 22px 紧凑层级，状态筛选紧邻标题区，项目行至少 66px 高并包含 34px 图标容器、22px 状态标识和 34px 直接进入按钮，列表从内容区左边界延伸到右边界

#### Scenario: 直接进入项目
- **WHEN** 项目行加载成功
- **THEN** 行尾显示文字为“进入项目”的可访问链接，生命周期和删除等次级操作收纳在其后的更多菜单

#### Scenario: 只展示真实项目信息
- **WHEN** 后端只返回目标与背景和目录节点数，未返回知识、候选或更新时间统计
- **THEN** 项目行只显示真实字段或缺省说明，不使用原型静态统计补齐信息

#### Scenario: 状态筛选保持稳定
- **WHEN** 用户切换四种生命周期筛选
- **THEN** 选中项使用白色表面、深色文字和轻阴影，未选中项使用透明背景与次要文字色，并且加载、空、错误状态不改变筛选栏尺寸
