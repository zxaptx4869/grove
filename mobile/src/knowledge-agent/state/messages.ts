/** 消息页状态：服务端 Run 为权威，按 id 归并且保持消息原序。 */

import type {
  KnowledgeMessage,
  KnowledgeMessagePage,
  KnowledgeRun,
} from "@/src/knowledge-agent/types";

export interface MessageThreadState {
  items: KnowledgeMessage[];
  runsById: Map<number, KnowledgeRun>;
  nextCursor: string | null;
  hasMore: boolean;
}

export function emptyThread(): MessageThreadState {
  return { items: [], runsById: new Map(), nextCursor: null, hasMore: false };
}

function dedupeById(items: KnowledgeMessage[]): KnowledgeMessage[] {
  const seen = new Set<number>();
  return items.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

function mergeRuns(
  previous: Map<number, KnowledgeRun>,
  incoming: KnowledgeRun[],
): Map<number, KnowledgeRun> {
  const next = new Map(previous);
  for (const run of incoming) {
    const existing = next.get(run.id);
    if (!existing || run.updatedAt >= existing.updatedAt) next.set(run.id, run);
  }
  return next;
}

export function applyRecentPage(
  state: MessageThreadState,
  page: KnowledgeMessagePage,
): MessageThreadState {
  return {
    items: dedupeById(page.items),
    runsById: mergeRuns(state.runsById, page.runs),
    nextCursor: page.nextCursor,
    hasMore: page.nextCursor !== null,
  };
}

export function prependOlderPage(
  state: MessageThreadState,
  page: KnowledgeMessagePage,
): MessageThreadState {
  const existingIds = new Set(state.items.map((item) => item.id));
  const pageOnly = page.items.filter((item) => !existingIds.has(item.id));
  return {
    items: [...pageOnly, ...state.items],
    runsById: mergeRuns(state.runsById, page.runs),
    nextCursor: page.nextCursor,
    hasMore: page.nextCursor !== null,
  };
}

export function upsertMessage(
  state: MessageThreadState,
  message: KnowledgeMessage,
): MessageThreadState {
  const index = state.items.findIndex((item) => item.id === message.id);
  if (index < 0) return { ...state, items: [...state.items, message] };
  const items = [...state.items];
  items[index] = message;
  return { ...state, items };
}

export function upsertRun(
  state: MessageThreadState,
  run: KnowledgeRun,
): MessageThreadState {
  return { ...state, runsById: mergeRuns(state.runsById, [run]) };
}

export function composeThread(
  recent: KnowledgeMessagePage | undefined,
  olderPages: KnowledgeMessagePage[],
  runOverrides: Map<number, KnowledgeRun>,
  extraMessages: KnowledgeMessage[],
): MessageThreadState {
  if (!recent) return emptyThread();
  let state = applyRecentPage(emptyThread(), recent);
  for (let index = olderPages.length - 1; index >= 0; index -= 1) {
    state = prependOlderPage(state, olderPages[index]);
  }
  for (const run of runOverrides.values()) state = upsertRun(state, run);
  for (const message of extraMessages) state = upsertMessage(state, message);
  return state;
}
