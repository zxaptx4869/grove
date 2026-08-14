## Context

处理管道已有 `ProcessingTask` 状态机和 `ProcessingProvider` 抽象，但 Demo 处理只是空转。AI 底座已接入 PydanticAI、DeepSeek 文本与豆包视觉，密钥由用户 BYOK 配置。本 change 让 Organizing Agent 真正从 Source 产出 `Extraction` 与 `Candidate`，视觉 OCR 保持解耦。

## Goals / Non-Goals

**Goals:**

- 新增 `Extraction` 与 `Candidate` 模型。
- 实现 Organizing Agent 结构化输出。
- 文字直接解析，图片经豆包视觉 OCR 后交给文本 Agent。
- 处理 Provider 接 Organizing Agent，并保证重试版本化、幂等、不覆盖。
- 提供最小候选查询 API 与前端只读预览。

**Non-Goals:**

- 不做确认台、Entry、目录推荐、关系判断。
- 不做像素级证据框选。
- 不做真实 OCR 评测集。
- 不自动触发处理。

## Decisions

### D1：处理输入流水线

处理服务按附件顺序组装文本上下文：

- `text` 附件直接加入，标记 `attachment_id`；
- `image` 附件先调用 `get_vision_model` 做 OCR/文字抽取，OCR 文本再标记 `attachment_id` 加入；
- `source.note` 作为高优先级说明；Source 归属 Project 时附加项目说明。

`EvidenceRef` 使用 `attachment_id + quote`，审阅时可按 `attachment_id` 回看原图。

### D2：结构化输出

PydanticAI Agent 的 `result_type` 定义为：

- `CandidateDraft`：`candidate_kind`、`title`、`content`、`main_type`、`info_nature`、`applicable_condition`、`note`、`evidence`、`reason`、`risk_flags`。
- `ExtractionDraft`：`candidates`、`discarded_count`、`discarded_reason_summary`。

`main_type` 四档：知识 / 方法 / 参数 / 提醒。`candidate_kind` 两档：推荐候选 / 其他发现。无效内容不落 Candidate。

### D3：数据模型

新增 `extractions` 与 `candidates` 表：

- `extractions`：`source_id`（FK）、`provider`、`model`、`prompt_version`、`status`（active / superseded / failed）、`discarded_count`、`discarded_reason_summary`、`error`、`created_at`。
- `candidates`：`extraction_id`、`source_id`（冗余便于查询）、`candidate_kind`、`title`、`content`、`main_type`、`info_nature`、`applicable_condition`、`note`、`evidence_refs`（JSON）、`reason`、`risk_flags`（JSON）、`status`（pending）。

`Candidate.status` 本轮固定为 `pending`，给后续审阅台扩展。

### D4：版本化与幂等

每次处理尝试创建一条 Extraction：

- 成功：新 Extraction `active`，之前所有成功 Extraction 置为 `superseded`；
- 失败：新 Extraction `failed`，上一份 `active` 保持不变；
- 当前候选只查询 `active` Extraction 下的 Candidate。

不删除历史 Extraction/Candidate，满足可审计与不覆盖。

### D5：处理 Provider 接入

`OrganizingProcessingProvider` 替换现有 `DemoProcessingProvider` 作为默认实现：

- 读取附件与 OCR 文本；
- 调 Organizing Agent 生成 `ExtractionDraft`；
- 落 `Extraction` + `Candidate`。

离线模式使用 PydanticAI 确定性测试模型，返回固定格式示例候选；真实模式使用 DeepSeek 文本与豆包视觉。

### D6：Candidate 查询 API

- `GET /api/sources/{source_id}/candidates`：返回当前 active Extraction 的 Candidate（只读）。
- 候选响应包含证据引用，但本轮不做确认动作。

### D7：前端最小预览

在来源列表/详情中提供「查看候选」只读入口，展示标题、类型、内容与证据片段；明确标注「AI 候选」，不使用正式知识文案。

### D8：测试策略

- 后端用离线模型测试确定性输出与版本化幂等；
- 视觉 OCR 与 Organizing Agent 用假实现隔离测试；
- 前端测试候选预览展示与 AI 候选文案。

## Risks / Trade-offs

- [视觉 OCR 质量影响候选质量] → 视觉解析独立，后续可替换 Provider 或做评测。
- [真实模型结构化输出失败] → PydanticAI 有界重试，仍失败则 Extraction failed，保留上一份 active。
- [JSON 字段可读性] → evidence_refs 与 risk_flags 使用 JSON，前端渲染时解析。
- [离线样例候选不够真实] → 仅用于验收流程，真实数据由真实 Provider 跑。

## Migration Plan

新增 Alembic 迁移创建 `extractions` 与 `candidates`，无需回填历史数据；已有 Source 无候选，处理后可生成。

## Open Questions

- 离线样例候选的具体内容在实现时以最小可用集为准。
- `prompt_version` 先使用常量，后续提示迭代再版本化。
