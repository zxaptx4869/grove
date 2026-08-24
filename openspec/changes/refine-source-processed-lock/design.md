## Context

上一 change 的保护只覆盖「已确认候选/证据」与「唯一证据」，未按产品确认的「done 来源整体锁定」落地。同时来源历史页搜索缺少清空与自动回到全部的能力。

## Goals / Non-Goals

**Goals:**

- done 来源后端拒绝改归属/删除，前端隐藏对应操作；
- 搜索输入防抖自动查询，提供清空按钮，清空后回到全部。

**Non-Goals:**

- 不改变 waiting/processing/failed 的现有操作；不为 done 来源新增删除/移动途径。

## Decisions

### D1：done 锁定（后端）

- `update_source`：先判 `project_locked`（既有），再判 `source.status == DONE` → 409「来源已处理完成，不能修改归属」；
- `delete_source`：先判唯一证据（既有），再判 `source.status == DONE` → 409「来源已处理完成，不能删除」。

顺序保证既有错误语义不变（归档来源仍提示"正式知识引用"，唯一证据仍提示"唯一来源证据"）。

### D2：done 锁定（前端）

`SourceList` 对 `status === 'done'` 的行不渲染改归属下拉与删除按钮；`project_locked` 禁用逻辑保留（覆盖非 done 但有证据的边界场景）。

### D3：搜索交互

`SourceHistoryPage` 用 300ms 防抖自动提交查询（异步 setState，符合 lint 规则），输入清空后自动回到全部；提供清空按钮（X）一键清空输入并回到全部。

## Risks / Trade-offs

- [done 来源有待确认候选时也无法删除/移动] → 产品确认的规则；如需清理走候选/Entry 处理，后续再评估专门入口。

## Migration Plan

无数据库变更。

## Open Questions

- 无。
