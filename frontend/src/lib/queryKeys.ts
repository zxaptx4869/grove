/** TanStack Query 查询键集中管理。失效时使用顶层前缀以覆盖所有子键。 */
export const queryKeys = {
  me: ['me'],
  projects: ['projects'],
  sources: ['sources'],
  projectTree: (projectId: number) => ['project-tree', projectId],
  projectContext: (projectId: number) => ['project-context', projectId],
  aiSettings: ['ai-settings'],
  sourceCandidates: (sourceId: number) => ['source-candidates', sourceId],
  reviewSources: (projectId: number) => ['review-sources', projectId],
  nodeEntries: (projectId: number, nodeId: number) => ['node-entries', projectId, nodeId],
} as const
