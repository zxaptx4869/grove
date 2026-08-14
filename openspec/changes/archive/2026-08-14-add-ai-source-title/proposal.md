## Why

采集阶段 Source 标题目前是纯规则生成：图片取文件名（粘贴图常为 `image.png`），文字取首行。这样在列表中难以识别。既然 Organizing Agent 在处理时已经能理解图片 OCR 文本与文字内容，可以在处理成功后生成一个更准确的标题。

## What Changes

- 修改 `extraction` 能力：
  - `ExtractionDraft` 增加 `source_title` 字段；
  - 处理成功后用 `source_title` 更新 `Source.title`，文字与图片 Source 都适用。
- 修改 `source-management` 能力：
  - 采集阶段仍使用规则初始标题；
  - 处理完成后允许 AI 标题覆盖初始标题。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `extraction`: Organizing Agent 输出新增 `source_title`，并在成功后更新 Source 标题。
- `source-management`: 标题生成规则扩展为「初始规则标题 + 处理成功后 AI 标题」。

## Impact

- 后端：修改 Organizing Agent 输出模型与提示词、离线样例标题、处理 Provider 成功回写 Source 标题。
- 前端：无需新增界面，来源列表会显示处理后的新标题。
- 无新表或迁移。

## Non-Goals

- 不在采集阶段异步生成标题。
- 不做标题人工编辑入口。
- 不做多轮标题候选或用户选择。
