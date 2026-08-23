## Context

上一 change（`add-entry-version-history-and-revision`，已归档）实现 AI 修订建议时，「不产生内容」只靠可空 `draft` 表达，提示词写成长篇硬约束仍挡不住模型在讨论时硬给草稿。讨论已确认采用档位 2：显式 `intent: discuss | propose`，让「讨论还是提出草稿」成为结构化的二选一。旧项目 KnowStruct 的 `apply_directory_tree` 工具调用（档位 3）作为更强兜底记录在 `docs/discussions/AI对话中讨论与内容输出的区分.md`。

## Goals / Non-Goals

**Goals:**

- Revision Agent 输出带显式 `intent`，提示词收回为一句规则；
- 应用层按意图归一化，非法组合降级为 `discuss` 并告警；
- 前端按 `intent` 决定只追加回复或更新草稿，讨论轮不动已有草稿。

**Non-Goals:**

- 不做工具调用（档位 3）；
- 不持久化会话与消息；
- 不改目录共创（保持档位 1）。

## Decisions

### D1：输出结构增加 `intent`

`RevisionReplyDraft` 增加 `intent: Literal["discuss", "propose"]`（默认 `discuss`），`reply_text` 与可空 `draft` 保持不变。响应 `RevisionSuggestionOut` 同样携带 `intent`。

理由：档位 2 的核心是把「二选一」变成协议字段，模型必须显式选择；默认 `discuss` 保证离线/异常路径安全。

### D2：提示词收敛为一句规则

替换原第 6-8 条硬约束为一句：「只有用户明确要求修改时 `intent=propose` 并返回完整草稿；提问、求证、讨论、质疑时 `intent=discuss`、`draft` 为 null，只返回文字」。避免长篇叮嘱，把约束交给结构。

### D3：应用层归一化

新增 `_normalize_revision_reply`：

- `intent=discuss` 但携带 `draft` → 丢弃草稿，记告警日志；
- `intent=propose` 但缺少 `draft` → 降级为 `discuss`，记告警日志；
- 其余情况原样返回。

理由：模型输出始终是候选，非法组合由确定性规则兜底，与关系建议的降级风格一致。

### D4：前端按意图处理

`generate` / `refine` 收到响应后：`intent=propose` 且有草稿 → 更新草稿表单；`intent=discuss` → 只追加回复，已有草稿保持不变。后端归一化已保证响应一致，前端按 `intent` 判断是第二道保险。

## Risks / Trade-offs

- [模型仍可能填错 intent] → 应用层按 D3 归一化，非法组合不会进入草稿更新路径。
- [显式字段增加输出约束] → 结构字段对 OpenAI 兼容模型成本极低，且比提示词硬约束更可靠。
- [目录共创仍是档位 1，体验不一致] → 记录为单独评估项，不随本 change 扩散范围。

## Migration Plan

无数据库变更；纯接口/输出结构调整，向前兼容（`intent` 为新增字段）。

## Open Questions

- 目录共创是否统一升级为档位 2，待修订建议验证后再单独评估。
