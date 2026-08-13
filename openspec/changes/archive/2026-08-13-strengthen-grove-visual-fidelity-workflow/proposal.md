## Why

现有 Grove UI Skill 要求关键页面进行原型截图对照，但没有规定编码前先提取视觉基线、用单一主视口收敛差异、检查浏览器计算样式或按任务风险选择验收强度，导致实现容易先采用框架默认值，再通过多轮用户反馈追赶原型。需要把已验证有效的视觉对齐方法沉淀为可触发、可执行、可验收的仓库级流程。

## What Changes

- 增强 `grove-ui-conventions` 的触发描述，明确覆盖原型还原、设计稿对齐、视觉精修和视觉验收任务。
- 为涉及原型的页面增加编码前视觉基线门禁、1440px 主视口收敛、截图与计算样式双重验证、多视口扩展和有意偏离记录流程。
- 增加单层渐进式参考文件，保存视觉基线表、Definition of Ready、Definition of Done、验收矩阵和 `design.md` 记录模板。
- 增加轻量视觉改动与完整页面对齐的任务分流，避免微小文案或非视觉任务承担完整截图矩阵成本。
- 更新 Skill 的 UI 元数据和 `frontend-foundation` 主规格对应要求。
- Non-Goals：不新建与 Grove UI Skill 重叠的独立 Skill；不编写截图自动化脚本；不修改产品页面、设计令牌、后端接口、数据库或产品范围。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `frontend-foundation`：强化 Grove UI Skill 对原型覆盖页面的实施前基线、任务分流、计算样式和多视口视觉验收要求。

## Impact

影响 `.codex/skills/grove-ui-conventions/`、其 `agents/openai.yaml`、新增的视觉对齐参考文件和 `openspec/specs/frontend-foundation/spec.md`。无业务代码、API、依赖、数据库或运行时影响。
