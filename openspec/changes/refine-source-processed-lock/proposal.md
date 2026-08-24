## Why

上一 change（`add-source-history-and-protections`）只按「已确认候选/证据」与「唯一证据」做了来源保护，但产品确认的规则是「已处理完成（status=done）的来源不再展示改归属与删除操作」。当前 done 来源仍可改归属/删除，且来源历史页搜索框缺少清空与回到全部数据的交互。

## What Changes

- `status=done` 的来源：后端禁止改归属与删除（409，可读原因）；前端隐藏改归属下拉与删除按钮。
- 来源历史页搜索框：增加清空按钮；输入防抖自动查询，清空后自动回到全部数据。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `source-management`: 已处理完成（done）来源禁止改归属与删除；SourceList 不展示对应操作。

## Impact

- 后端：`api/sources.py` 改归属/删除增加 done 校验（先于既有锁/唯一证据校验之外，保持既有错误语义）。
- 前端：`SourceList.tsx` 隐藏 done 来源的改归属与删除；`SourceHistoryPage.tsx` 搜索防抖 + 清空按钮。
- 测试：后端 done 改归属/删除 409；前端清空回到全部、done 来源不显示操作。
- 数据与依赖：无迁移、无新增依赖。

## Non-Goals

- 不改 waiting/processing/failed 来源的现有操作；不为已处理来源提供新的删除/移动途径。
