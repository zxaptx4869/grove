## Why

确认台已经能把 Candidate 置为已采纳，但这些采纳结果还没有成为正式知识。可信整理闭环需要把已采纳候选落成 `Entry`，并保留到 Source 的证据关系；同时用户要能编辑、移动到正确目录。

## What Changes

- 新增 `entry` 能力：
  - `Entry` 模型：归属 Project，必选主目录节点；
  - `EntrySourceEvidence`：Entry 与 Source/Attachment 证据关系；
  - 采纳并归档：确认台选目录后原子创建 Entry，并把 Candidate 关联到 Entry；
  - Entry 编辑与移动目录：基础修改记录为时间戳。
- 修改 `candidate-review` 能力：
  - 采纳必须选择目录并创建 Entry；
  - 已归档候选锁定，不再允许重新打开。

## Capabilities

### New Capabilities

- `entry`: Entry 模型、来源证据关系、采纳并归档、编辑与移动目录。

### Modified Capabilities

- `candidate-review`: 采纳动作升级为创建 Entry，已归档候选锁定。

## Impact

- 后端：新增 Entry 与 EntrySourceEvidence 模型及迁移、归档 API、Entry 编辑 API。
- 前端：确认台候选编辑区增加目录选择器，采纳后创建 Entry；知识空间可展示正式知识。
- 无新外部依赖。

## Non-Goals

- 不做标签。
- 不做完整版本历史表。
- 不做目录节点推荐（`add-project-and-node-routing-suggestions`）。
- 不做无合适目录时的「新增节点并归档」（`add-create-node-and-archive`）。
- 不做 Entry 卡片/列表切换和搜索。
