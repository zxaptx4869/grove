/** TanStack Query 键：会话、消息页与 Run 的缓存归属。 */

export const knowledgeAgentKeys = {
  all: ["knowledge-agent"] as const,
  conversations: () => ["knowledge-agent", "conversations"] as const,
  conversation: (id: number) => ["knowledge-agent", "conversation", id] as const,
  messages: (id: number) => ["knowledge-agent", "messages", id] as const,
  run: (id: number) => ["knowledge-agent", "run", id] as const,
};
