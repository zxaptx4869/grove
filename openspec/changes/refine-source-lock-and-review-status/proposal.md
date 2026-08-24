## Why

上一 change 把来源的锁定绑定在 `status=done` 上，但 `done` 只是「提取完成」，不代表候选已确认成正式知识——导致提取完成但候选尚未确认的来源也无法改归属/删除，过度锁定。正确规则应是「来源已产生至少一条正式知识才锁定」。同时用户无法从列表看出候选确认状态，需要把审阅状态展示出来；「已完成」文案与提取语义混淆，改为「提取完成」。

## What Changes

- 锁定条件修正：改归属/删除仅在来源**已产生正式知识**（存在已确认候选或 Entry 证据）时禁止；去掉按 `done` 的锁定。
- 处理中（processing）期间临时禁止改归属与删除。
- 删除有待确认候选的来源时，前端二次确认并提示将连带删除候选。
- 来源列表展示候选确认副状态（待确认 N 条 / 部分确认 / N 条正式知识 / 已处理），锁定原因可见。
- 主状态文案「已完成」改为「提取完成」；`SourceOut` 返回 `pending_candidate_count`。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `source-management`: 锁定条件、审阅状态展示、状态文案与处理中锁定。

## Impact

- 后端：`api/sources.py`（去掉 done 锁、加 processing 锁、删证据即禁删、批量返回 pending_candidate_count）、`schemas/source.py`。
- 前端：`SourceList`（文案、副徽标、操作可见性、删除确认）。
- 测试：后端锁定/解锁矩阵；前端副徽标与确认用例。
- 数据与依赖：无迁移、无新增依赖。

## Non-Goals

- 不为已产生正式知识的来源提供删除/移动途径。
- 不改确认台候选流程。
