## Context

当前 `DemoProjectContextGenerator` 把 `select(Node).order_by(Node.position)` 返回的全部节点名都放进 `directory_topics`。对默认空目录项目没问题，但对兼容旧模板生成的 149 节点装修项目，首页会渲染大量标签，且这些叶子节点不是「主题」。

## Goals / Non-Goals

**Goals:**

- `directory_topics` 只取顶级目录节点（`parent_id IS NULL`）。
- 前端对超长目录主题列表做数量上限与剩余提示。

**Non-Goals:**

- 不做真实 Provider 的目录主题摘要。
- 不改动 `ProjectContext` 数据模型与 API 结构。
- 不提供目录主题独立纠正。

## Decisions

### D1：目录主题取顶级目录节点

生成器只保留 `parent_id IS None` 的节点名。顶级节点是用户对项目知识空间的一级主题划分，最适合作为「目录主题」摘要；叶子节点由正式目录树本身承载，不必在首页重复展开。

### D2：前端折叠展示

`ProjectContextPanel` 设置 `MAX_TOPIC_BADGES = 8`：超过时显示前 8 个并追加 `+N` 徽标。这样即使未来目录主题较多，也不会撑爆页面。

## Risks / Trade-offs

- [顶级节点为空但存在子节点] → 当前目录模型不会出现无顶级节点而有子节点；如异常数据导致为空，前端按空目录处理。
- [展示上限硬编码] → 先取 8，后续真实使用可按页面宽度或用户偏好调整。

## Migration Plan

无数据库迁移；仅改 Demo 生成器与前端展示。

## Open Questions

- 顶级节点数量较多时是否需要按「最近活跃」或「用户排序」进一步裁剪（留待后续数据验证）。
