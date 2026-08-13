## MODIFIED Requirements

### Requirement: 样式体系与基础组件
前端 MUST 配置 Tailwind 4，并初始化 shadcn/ui 基础（至少包含按钮组件与 `utils` 工具）；产品业务页面 SHALL 按桌面知识工作台设计，从 1024px 视口宽度开始支持完整流程，不要求在手机宽度下重排或提供业务操作。

#### Scenario: 桌面工作台宽度可用
- **WHEN** 以 1280px 视口宽度渲染产品业务页面
- **THEN** 页面无非预期横向滚动，核心内容、导航和操作完整可见

### Requirement: Grove 仓库级 UI skill
仓库 MUST 包含 `.codex/skills/grove-ui-conventions/SKILL.md`，该 skill SHALL 在 Grove 前端实现、调整或 UI 验收任务中触发，并 SHALL 以产品蓝图与 OpenSpec 定义产品行为、以 `frontend/src/index.css` 定义设计令牌、以现有组件代码定义接口，避免复制易漂移的第二份事实来源。

#### Scenario: 前端任务加载产品专属约束
- **WHEN** 代理实施或调整 Grove 前端页面、产品组件或交互状态
- **THEN** skill 能引导代理读取相关蓝图、规格、主题和代码，并检查 AI 候选与正式 Entry 区分、来源可达、状态完整、可访问性、桌面工作台布局和小屏产品边界

#### Scenario: skill 结构有效
- **WHEN** 使用 skill-creator 的 `quick_validate.py` 校验 `.codex/skills/grove-ui-conventions`
- **THEN** 校验成功且 skill 元数据与目录命名有效

## ADDED Requirements

### Requirement: 端侧产品边界可追溯
仓库的产品蓝图、代理守则与 Grove UI skill MUST 一致声明：Web 只承担桌面完整业务流程，手机 Web 不属于业务流程验收范围；原生 App 上线前的小屏访问 SHALL 规划为统一的电脑访问提示，不提供简化版工作台或继续访问入口。

#### Scenario: 协作者确认 Web 支持范围
- **WHEN** 协作者准备设计或实施 Grove 产品页面
- **THEN** 能从权威文档中确认桌面支持宽度、手机 Web 非目标以及后续小屏阻断页要求
