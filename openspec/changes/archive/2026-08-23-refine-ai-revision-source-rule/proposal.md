## Why

应用 AI 修订时，只要字段有实际变化就创建「AI 修订建议」虚拟 Source 并追加来源证据，导致纯格式/表述调整也产生冗余来源（实测：同一 Entry 出现两条 AI 来源，第二次只是调格式）。虚拟 Source 的用途是让"非既有材料支撑的内容"可溯源；信息未变的内部整理仍由原来源支撑，不需要新增来源。

## What Changes

- 应用 AI 修订草稿时，仅当草稿标记 `external_supplemented=true`（AI 带入了外部知识/新信息）才创建虚拟 Source 与来源证据；
- 纯格式/表述调整（`external_supplemented=false`）仍追加 `ai_revision` 版本与变更说明，但不新增来源证据；
- 应用请求新增 `external_supplemented` 回传，前端在应用时随草稿一起提交。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `entry`: 「应用 AI 修订建议」需求更新——虚拟 Source 只在外部补充时创建。

## Impact

- 后端：`schemas/entry.py` 应用请求增加 `external_supplemented`；`services/entry.py` 创建虚拟 Source 的条件改为 `external_supplemented=true`。
- 前端：`lib/api.ts` 类型、`RevisionSuggestionDialog.tsx` 应用时回传标记。
- 测试：后端新增 external=false 不建来源、external=true 建来源用例；前端断言应用请求携带标记。
- 数据与依赖：无迁移、无新增依赖；已有冗余来源保留（演示数据不清理）。

## Non-Goals

- 不改变版本记录行为（格式调整仍记版本）。
- 不清理已有演示数据中的冗余来源。
- 不引入"是否实质修改"的新模型字段（以 `external_supplemented` 为准）。
