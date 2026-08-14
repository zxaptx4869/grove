## Why

处理管道已经能跑通状态机，但 `ProcessingProvider` 目前只是空转的 Demo，Source 处理后不会产生任何可确认内容。可信整理闭环的核心是：把 Source 变成可审阅的 `Candidate`，同时用版本化 `Extraction` 保留 AI 的运行与审计信息。这一项接入 Organizing Agent，让图片/文字真正被解析、拆分并产出候选，但不做确认台和 Entry。

## What Changes

- 新增 `extraction` 能力：
  - `Extraction` 模型：归属 Source，版本化记录模型、提示、结构化输出、错误与状态；
  - `Candidate` 模型：归属 Extraction，承载标题、核心内容、主类型、信息性质、证据引用、推荐理由与风险信号；
  - Organizing Agent：基于 PydanticAI 结构化输出候选，文字直接解析，图片先由豆包视觉 OCR 再交给文本 Agent；
  - 幂等重试：新成功 Extraction 取代旧成功 Extraction 成为 active，失败保留上一份 active，不复制 Candidate；
  - 无效内容不落 Candidate，只在 Extraction 上记录数量与摘要。
- 修改 `processing-task` 能力：
  - 处理 Provider 默认改为 Organizing 处理 Provider，离线模式仍确定性，真实 Provider 通过 Organizing Agent 执行。

## Capabilities

### New Capabilities

- `extraction`: Extraction 与 Candidate 模型、Organizing Agent 结构化输出、视觉 OCR 解耦、版本化幂等重试与证据引用。

### Modified Capabilities

- `processing-task`: 处理 Provider 从空转 Demo 改为 Organizing 处理 Provider。

## Impact

- 后端：新增 Extraction/Candidate 模型与迁移、Organizing Agent 服务、视觉 OCR 文本组装、处理 Provider 实现、Candidate 查询 API。
- 前端：Source 详情或来源列表提供最小候选预览（只读），用于验收；不做确认交互。
- 依赖：复用已接入的 PydanticAI、DeepSeek 文本与豆包视觉 Provider。
- 无 Entry、确认台或目录推荐。

## Non-Goals

- 不做 Source 审阅台、候选确认/拒绝/暂缓/合并。
- 不做 Entry 与来源证据关系。
- 不做目录节点推荐（`add-project-and-node-routing-suggestions`）。
- 不做与已有 Entry 的关系判断（`add-entry-relation-suggestions`）。
- 不做真实中文截图 OCR 的完整质量评测集。
- 不自动触发处理，保持现有手动「开始处理」。
