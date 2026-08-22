## MODIFIED Requirements

### Requirement: 思维导图项目级入口
系统 SHALL 将思维导图作为知识全景视图（`view=overview`）内的模式提供（`mode=mindmap`），不再提供独立 `view=mindmap` 入口；模式切换 SHALL 位于知识全景顶部「旭日图 | 思维导图」；处于思维导图模式时 SHALL 隐藏应用壳左侧栏，画布占满窗口宽度，顶部极简阅读栏 SHALL 提供返回知识空间、项目名、阅读侧栏开关与模式切换；思维导图模式 SHALL 提供「查看全景」返回旭日图模式并保持当前节点。

#### Scenario: 从知识空间进入
- **WHEN** 用户在知识空间页头点击「知识全景」入口并切换或直接进入思维导图模式
- **THEN** 页面处于知识全景视图的思维导图模式（`view=overview&mode=mindmap`）

#### Scenario: 从项目首页进入
- **WHEN** 用户在项目首页目录入口区域点击「知识全景」入口并切换或直接进入思维导图模式
- **THEN** 页面处于知识全景视图的思维导图模式（`view=overview&mode=mindmap`）

#### Scenario: 沉浸式无壳
- **WHEN** 用户处于思维导图模式
- **THEN** 应用壳左侧栏不显示，画布与阅读侧栏占满窗口宽度，顶部极简阅读栏显示返回入口、项目名、阅读侧栏开关与模式切换

#### Scenario: 返回知识空间
- **WHEN** 用户点击顶栏「返回知识空间」
- **THEN** 页面返回 `view=directory`，应用壳左侧栏恢复显示

#### Scenario: 查看全景
- **WHEN** 用户在思维导图模式点击「查看全景」
- **THEN** 切回旭日图模式并保持当前节点
