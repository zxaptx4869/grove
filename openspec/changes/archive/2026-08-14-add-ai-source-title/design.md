## Context

当前 `ExtractionDraft` 只包含候选与丢弃摘要，`Source.title` 在采集时按规则生成。Organizing Agent 已有完整输入上下文，适合顺带生成更准确的标题。

## Goals / Non-Goals

**Goals:**

- `ExtractionDraft.source_title` 增加标题输出。
- 处理成功后更新 `Source.title`。
- 离线模式输出确定性标题。

**Non-Goals:**

- 不在采集阶段调用 AI。
- 不做标题人工编辑或候选选择。

## Decisions

### D1：标题作为 ExtractionDraft 字段

`source_title: str` 加入结构化输出；提示词要求生成简洁、可识别的标题，不超过 120 字。

### D2：成功后回写 Source.title

`OrganizingProcessingProvider.process` 成功后，若 `source_title` 非空，则写入 `loaded.title`，截断到 255 字。失败时保留原标题。

### D3：离线确定性标题

离线模式从第一个文本/OCR 片段截取前 40 字作为标题；无文本时回退原 `Source.title`。

## Risks / Trade-offs

- [真实模型标题可能过长] → 后端截断到 255 字，提示词限制简洁。
- [标题更新依赖处理成功] → 失败时保持初始标题，不影响采集。

## Migration Plan

无数据库迁移。

## Open Questions

- 标题长度上限先取 120 字提示约束，落库仍截 255 字。
