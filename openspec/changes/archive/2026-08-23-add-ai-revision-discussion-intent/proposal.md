## Why

AI 修订建议对话在讨论、提问时仍会强制输出修订草稿（实测：问「缝隙消失术真的是噱头吗」仍返回草稿），交互死板。根因是「不产生内容」只靠可空 `draft` 字段表达，结构约束弱、主要靠提示词硬约束。需要把「讨论 vs 提出草稿」变成模型显式二选一的结构决策（档位 2：`intent`）。

## What Changes

- Revision Agent 输出增加显式意图 `intent: discuss | propose`；
- 提示词收敛为一句规则：只有用户明确要求修改时 `intent=propose` 并返回完整草稿；提问、求证、讨论、质疑时 `intent=discuss`、`draft` 为 null，只返回文字；
- 应用层归一化：`intent=discuss` 时忽略模型误带的草稿；`intent=propose` 却缺少草稿时降级为 `discuss`，并记录告警日志；
- 响应携带 `intent`，前端按意图决定「只追加回复」还是「更新草稿」；已有草稿在讨论轮保持不动。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `entry`: 「AI 修订建议生成与对话调整」需求补充讨论模式——对话 MUST 区分讨论与提出草稿，通过显式 `intent` 结构化表达。

## Impact

- 后端：`agents/revision.py`（输出结构 + 提示词）、`schemas/entry.py`（响应加 `intent`）、`services/entry.py`（归一化与告警日志）。
- 前端：`lib/api.ts` 类型、`RevisionSuggestionDialog.tsx` 按 `intent` 更新草稿。
- 测试：后端离线降级断言、归一化单测；前端 mock 带 `intent` 的讨论/提出用例。
- 数据与依赖：无数据变更，无新增依赖。

## Non-Goals

- 不做档位 3 工具调用（`apply_revision_draft`）；升级路径记录在 `docs/discussions/AI对话中讨论与内容输出的区分.md`。
- 不持久化会话与消息。
- 不改目录共创（保持档位 1：可空 `tree` + 一句规则），统一升级留待单独评估。
