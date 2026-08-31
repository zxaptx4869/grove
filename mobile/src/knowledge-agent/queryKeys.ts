/** TanStack Query 键：会话、消息页与 Run 的缓存归属。 */

export const knowledgeAgentKeys = {
  all: ["knowledge-agent"] as const,
  conversations: () => ["knowledge-agent", "conversations"] as const,
  conversation: (id: number) => ["knowledge-agent", "conversation", id] as const,
  messages: (id: number) => ["knowledge-agent", "messages", id] as const,
  run: (id: number) => ["knowledge-agent", "run", id] as const,
  drafts: (conversationId: number) =>
    ["knowledge-agent", "drafts", conversationId] as const,
  draft: (id: number) => ["knowledge-agent", "draft", id] as const,
  revisionDrafts: (conversationId: number) =>
    ["knowledge-agent", "revision-drafts", conversationId] as const,
  revisionDraft: (id: number) =>
    ["knowledge-agent", "revision-draft", id] as const,
  /** 引用弹窗展示的当前正式知识（按 Entry id 缓存，避免重复请求）。 */
  entryCurrent: (entryId: number) =>
    ["knowledge-agent", "entry-current", entryId] as const,
};
