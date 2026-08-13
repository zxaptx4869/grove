## Why

已确认的 Grove 产品原型目前只存在于会话生成目录，既未纳入版本管理，也没有说明它与产品蓝图、OpenSpec 和正式前端代码的关系。需要将原型作为可追踪的设计参考资产入库，让后续 change 能按页面引用并进行视觉验收，同时避免原型演示内容被误认为已实现行为。

## What Changes

- 将 2026-08-13 确认的桌面产品原型迁入 `docs/prototypes/`，保留可交互的单文件 HTML。
- 为原型补充版本、覆盖页面、运行方式、权威边界和后续 OpenSpec 衔接说明。
- 在 README 增加原型入口，并在 Grove UI Skill 中增加“按需引用原型页面”的实施规则。
- 更新前端基础主规格，使原型资产及其与正式实现的边界可验证。

### Non-Goals

- 不修改 React 正式前端、API、数据库或业务行为。
- 不将原型中的静态数据、模拟交互和视觉细节提升为产品规格。
- 不要求后续一次性重写全部页面；每个 OpenSpec change 只引用并实现自身范围内的原型部分。
- 不把原型中的演示依赖引入正式前端依赖。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `frontend-foundation`：增加版本化产品原型、权威边界、按 change 引用和视觉验收要求。

## Impact

- 新增 `docs/prototypes/` 下的 HTML 与说明文档。
- 更新 `README.md`、Grove UI Skill 和 `openspec/specs/frontend-foundation/spec.md`。
- 不影响后端、前端构建产物、运行时依赖或部署。
