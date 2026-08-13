## Why

上一 change 的 Project Context Snapshot 把正式目录的**全部节点**都放进 `directory_topics`。装修模板等项目有 100+ 节点时，项目首页会渲染成一片标签墙，既不友好，也不符合「目录主题」的语义——主题应当是项目顶层的目录入口，而不是每个叶子节点。

## What Changes

- 修改 `project-context` 能力：
  - 生成初始概要时，`directory_topics` 只取顶级目录节点，不枚举全部叶子节点；
  - 项目首页对目录主题做折叠展示，超过上限只显示前若干个并提示剩余数量。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `project-context`: `directory_topics` 改为顶级目录节点；前端对超长目录主题折叠展示。

## Impact

- 后端：Demo 生成器改为只使用顶级目录节点；后端测试同步修正。
- 前端：`ProjectContextPanel` 增加目录主题数量上限与剩余数量展示；前端测试补充折叠场景。

## Non-Goals

- 不做真实 Provider 的目录主题摘要或语义合并。
- 不改动 `ProjectContext` 数据结构与 API 响应形状。
- 不提供用户对目录主题的独立纠正（用户应编辑正式目录本身）。
