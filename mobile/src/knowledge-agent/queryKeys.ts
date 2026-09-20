/** TanStack Query 键：正式对话、Run 与当前 Entry 的缓存归属。 */

export const knowledgeAgentKeys = {
  all: ["knowledge-agent"] as const,
  conversations: () => ["knowledge-agent", "conversations"] as const,
  conversation: (id: number) => ["knowledge-agent", "conversation", id] as const,
  messages: (id: number) => ["knowledge-agent", "messages", id] as const,
  run: (id: number) => ["knowledge-agent", "run", id] as const,
  /** 底部详情按需读取的当前正式知识；未打开详情时不发请求。 */
  entryCurrent: (entryId: number) =>
    ["knowledge-agent", "entry-current", entryId] as const,
};
