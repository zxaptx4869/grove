/** 消息页状态：最近页替换、向前分页 prepend 与按 id 去重。 */

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
  const result: KnowledgeMessage[] = [];
  for (const item of items) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    result.push(item);
  }
  return result;
}

/** 去重时保留后出现的版本（同一消息以较晚数据为准）。 */
function dedupeByIdPreferLast(items: KnowledgeMessage[]): KnowledgeMessage[] {
  return [...dedupeById([...items].reverse())].reverse();
}

function mergeRuns(
  runsById: Map<number, KnowledgeRun>,
  runs: KnowledgeRun[],
): Map<number, KnowledgeRun> {
  const next = new Map(runsById);
  for (const run of runs) {
    const existing = next.get(run.id);
    // 服务端数据是权威状态：同 id 时以更新的 updated_at 为准
    if (
      existing === undefined ||
      run.updatedAt >= existing.updatedAt
    ) {
      next.set(run.id, run);
    }
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
  // 更早页整体插到当前消息之前；重复消息只保留先出现（更晚）的一条
  const merged = dedupeByIdPreferLast([...page.items, ...state.items]);
  return {
    items: merged,
    runsById: mergeRuns(state.runsById, page.runs),
    nextCursor: page.nextCursor,
    hasMore: page.nextCursor !== null,
  };
}

export function upsertMessage(
  state: MessageThreadState,
  message: KnowledgeMessage,
): MessageThreadState {
  const items = dedupeByIdPreferLast([...state.items, message]);
  return { ...state, items };
}

export function threadFromPage(page: KnowledgeMessagePage): MessageThreadState {
  return applyRecentPage(emptyThread(), page);
}
