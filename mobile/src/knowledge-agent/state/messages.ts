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
  // 更早页整体插到当前消息之前：重复消息保留现有（更晚）版本及其位置，
  // 只把旧页独有的消息前置，不改变已有消息的相对顺序。
  const existingIds = new Set(state.items.map((item) => item.id));
  const pageOnly = page.items.filter((item) => !existingIds.has(item.id));
  const merged = [...pageOnly, ...state.items];
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
  const index = state.items.findIndex((item) => item.id === message.id);
  if (index >= 0) {
    // 同一消息已存在：原位替换内容，不改变消息顺序
    const items = [...state.items];
    items[index] = message;
    return { ...state, items };
  }
  return { ...state, items: [...state.items, message] };
}

export function upsertRun(
  state: MessageThreadState,
  run: KnowledgeRun,
): MessageThreadState {
  return { ...state, runsById: mergeRuns(state.runsById, [run]) };
}

export function threadFromPage(page: KnowledgeMessagePage): MessageThreadState {
  return applyRecentPage(emptyThread(), page);
}

/** 由服务端最近页、向前加载的旧页、轮询 Run 覆盖与本地提交消息组合线程。 */
export function composeThread(
  recent: KnowledgeMessagePage | undefined,
  olderPages: KnowledgeMessagePage[],
  runOverrides: Map<number, KnowledgeRun>,
  extraMessages: KnowledgeMessage[],
): MessageThreadState {
  if (!recent) return emptyThread();
  let state = threadFromPage(recent);
  for (let index = olderPages.length - 1; index >= 0; index -= 1) {
    state = prependOlderPage(state, olderPages[index]);
  }
  for (const run of runOverrides.values()) {
    state = upsertRun(state, run);
  }
  for (const message of extraMessages) {
    state = upsertMessage(state, message);
  }
  return state;
}
