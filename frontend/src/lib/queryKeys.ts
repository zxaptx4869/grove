/** TanStack Query 查询键集中管理。失效时使用顶层前缀以覆盖所有子键。 */
export const queryKeys = {
  me: ['me'],
  projects: ['projects'],
  sources: ['sources'],
  projectTree: (projectId: number) => ['project-tree', projectId],
  directoryDraft: (projectId: number) => ['directory-draft', projectId],
  projectContext: (projectId: number) => ['project-context', projectId],
  aiSettings: ['ai-settings'],
  sourceCandidates: (sourceId: number) => ['source-candidates', sourceId],
  reviewSources: (projectId: number) => ['review-sources', projectId],
  reviewCandidates: (projectId: number) => ['review-candidates', projectId],
  nodeEntries: (projectId: number, nodeId: number, scope: 'direct' | 'descendants') => [
    'node-entries',
    projectId,
    nodeId,
    scope,
  ],
  search: (q: string, projectId?: number) => ['search', q, projectId ?? 'global'],
} as const
