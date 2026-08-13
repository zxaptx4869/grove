## MODIFIED Requirements

### Requirement: Grove 仓库级 UI skill
仓库 MUST 包含 `.codex/skills/grove-ui-conventions/SKILL.md`，该 skill SHALL 在 Grove 前端实现、调整或 UI 验收任务中触发，并 SHALL 先读取产品蓝图索引、再按当前页面或交互任务读取相关专题，以 OpenSpec 定义产品行为、以 `frontend/src/index.css` 定义设计令牌、以现有组件代码定义接口，避免无差别加载全部蓝图文档或复制易漂移的第二份事实来源。

#### Scenario: 前端任务加载产品专属约束
- **WHEN** 代理实施或调整 Grove 前端页面、产品组件或交互状态
- **THEN** skill 能引导代理读取蓝图索引和当前任务相关专题，并检查 AI 候选与正式 Entry 区分、来源可达、状态完整、可访问性、桌面工作台布局和小屏产品边界

#### Scenario: skill 不加载无关专题
- **WHEN** 前端任务只涉及确认台、知识空间或其他单一产品领域
- **THEN** skill 不要求读取全部蓝图专题，而只加载索引、相关专题、当前规格、主题和代码

#### Scenario: skill 结构有效
- **WHEN** 使用 skill-creator 的 `quick_validate.py` 校验 `.codex/skills/grove-ui-conventions`
- **THEN** 校验成功且 skill 元数据与目录命名有效
