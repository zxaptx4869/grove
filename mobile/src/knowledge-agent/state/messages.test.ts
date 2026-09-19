import {
  applyRecentPage,
  composeThread,
  emptyThread,
  prependOlderPage,
  upsertRun,
} from "@/src/knowledge-agent/state/messages";
import type {
  KnowledgeMessage,
  KnowledgeMessagePage,
  KnowledgeRun,
} from "@/src/knowledge-agent/types";

function message(id: number): KnowledgeMessage {
  return {
    id,
    conversationId: 1,
    role: id % 2 ? "user" : "assistant",
    messageType: id % 2 ? "user" : "assistant",
    content: `消息 ${id}`,
    clientMessageId: null,
    runId: 1,
    scopeType: "workspace",
    projectId: null,
    projectName: null,
    requestContextMode: null,
    contextDecision: null,
    standaloneQuery: null,
    topicLabel: null,
    createdAt: new Date(id * 1000).toISOString(),
  };
}

function run(status: KnowledgeRun["status"], updatedAt: string): KnowledgeRun {
  return {
    id: 1,
    conversationId: 1,
    status,
    currentStep: null,
    scopeType: "workspace",
    projectId: null,
    projectName: null,
    userMessageId: 1,
    assistantMessageId: 2,
    cancelRequested: false,
    error: null,
    requestContextMode: "auto",
    contextDecision: null,
    standaloneQuery: null,
    topicLabel: null,
    answer: null,
    dialogueLoopStatus: status,
    dialogueStage: null,
    dialogueBlocks: [],
    canContinue: false,
    continuation: null,
    createdAt: updatedAt,
    updatedAt,
  };
}

function page(
  items: KnowledgeMessage[],
  runs: KnowledgeRun[],
  nextCursor: string | null = null,
): KnowledgeMessagePage {
  return { items, nextCursor, runs };
}

test("最近页与更早页保持服务端消息顺序并去重", () => {
  let state = applyRecentPage(emptyThread(), page([message(3), message(4)], [run("processing", "2")]));
  state = prependOlderPage(state, page([message(1), message(2), message(3)], []));
  expect(state.items.map((item) => item.id)).toEqual([1, 2, 3, 4]);
});

test("同一 Run 以更新的服务端终态覆盖进行中状态", () => {
  let state = applyRecentPage(emptyThread(), page([], [run("processing", "2")]));
  state = upsertRun(state, run("completed", "3"));
  expect(state.runsById.get(1)?.status).toBe("completed");
});

test("连续加载两页历史保持时间正序并采用最早页游标", () => {
  const state = composeThread(
    page([message(5), message(6)], [], "c1"),
    [
      page([message(3), message(4), message(5)], [], "c2"),
      page([message(1), message(2), message(3)], [], null),
    ],
    new Map(),
    [],
  );

  expect(state.items.map((item) => item.id)).toEqual([1, 2, 3, 4, 5, 6]);
  expect(state.nextCursor).toBeNull();
  expect(state.hasMore).toBe(false);
});
