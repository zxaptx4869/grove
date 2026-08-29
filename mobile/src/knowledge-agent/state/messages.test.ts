import {
  applyRecentPage,
  composeThread,
  emptyThread,
  prependOlderPage,
  upsertMessage,
  threadFromPage,
} from "@/src/knowledge-agent/state/messages";
import type {
  KnowledgeMessage,
  KnowledgeMessagePage,
  KnowledgeRun,
} from "@/src/knowledge-agent/types";

function message(id: number, content: string, runId: number | null = null): KnowledgeMessage {
  return {
    id,
    conversationId: 1,
    role: id % 2 === 0 ? "assistant" : "user",
    messageType: id % 2 === 0 ? "assistant" : "user",
    content,
    clientMessageId: null,
    runId,
    scopeType: "workspace",
    projectId: null,
    projectName: null,
    requestContextMode: null,
    contextDecision: null,
    standaloneQuery: null,
    topicLabel: null,
    requestAnswerMode: null,
    actualAnswerMode: null,
    currentRound: 0,
    inputContextVersionId: null,
    outputContextVersionId: null,
    createdAt: new Date(id).toISOString(),
  };
}

function run(id: number, updatedAt: string): KnowledgeRun {
  return {
    id,
    conversationId: 1,
    status: "completed",
    currentStep: null,
    scopeType: "workspace",
    projectId: null,
    projectName: null,
    userMessageId: null,
    assistantMessageId: null,
    cancelRequested: false,
    retryCount: 0,
    maxRetries: 1,
    error: null,
    requestContextMode: null,
    contextDecision: null,
    standaloneQuery: null,
    topicLabel: null,
    requestAnswerMode: null,
    actualAnswerMode: null,
    currentRound: 0,
    inputContextVersionId: null,
    outputContextVersionId: null,
    contextDegraded: false,
    fallbackSummary: null,
    investigationSummary: null,
    answer: null,
    createdAt: updatedAt,
    updatedAt,
  };
}

function page(
  items: KnowledgeMessage[],
  nextCursor: string | null,
  runs: KnowledgeRun[] = [],
): KnowledgeMessagePage {
  return { items, nextCursor, runs };
}

test("最近页替换旧内容并按 id 去重", () => {
  const recent = page([message(5, "五"), message(6, "六")], null, [run(6, "t2")]);
  const state = applyRecentPage(emptyThread(), recent);
  expect(state.items.map((item) => item.id)).toEqual([5, 6]);
  expect(state.hasMore).toBe(false);

  // 再次收到包含重复的首页数据：以服务端为准但保持去重
  const dup = page([message(5, "五"), message(5, "五改"), message(7, "七")], null);
  const next = applyRecentPage(state, dup);
  expect(next.items.map((item) => item.id)).toEqual([5, 7]);
});

test("向前分页 prepend 更早消息并去重", () => {
  const recent = page([message(5, "五"), message(6, "六")], "cursor-6", [run(6, "t1")]);
  const state = applyRecentPage(emptyThread(), recent);
  const older = page([message(1, "一"), message(2, "二"), message(5, "五旧")], "cursor-2");
  const next = prependOlderPage(state, older);
  expect(next.items.map((item) => item.id)).toEqual([1, 2, 5, 6]);
  expect(next.items.find((item) => item.id === 5)?.content).toBe("五");
  expect(next.nextCursor).toBe("cursor-2");
  expect(next.hasMore).toBe(true);
});

test("同 id Run 以服务端更新的 updated_at 为准", () => {
  const first = threadFromPage(
    page([message(5, "五", 9)], "c", [run(9, "2026-08-01T00:00:00Z")]),
  );
  const second = prependOlderPage(
    first,
    page([message(1, "一", 9)], null, [run(9, "2026-08-02T00:00:00Z")]),
  );
  expect(second.runsById.get(9)?.updatedAt).toBe("2026-08-02T00:00:00Z");
  expect(second.runsById.size).toBe(1);
});

test("upsertMessage 已存在时原位替换，不改变消息顺序", () => {
  const state = threadFromPage(
    page([message(1, "一"), message(2, "二"), message(3, "三")], null),
  );
  const updated = upsertMessage(state, message(2, "二（新版本）"));
  expect(updated.items.map((item) => item.id)).toEqual([1, 2, 3]);
  expect(updated.items.find((item) => item.id === 2)?.content).toBe(
    "二（新版本）",
  );
  const appended = upsertMessage(state, message(4, "四"));
  expect(appended.items.map((item) => item.id)).toEqual([1, 2, 3, 4]);
});

test("两轮对话顺序保持 用户→回答→用户→回答，不因提交回填乱序", () => {
  const recent = page(
    [
      message(1, "第一轮问题", 10),
      message(2, "第一轮回答", 10),
      message(3, "第二轮问题", 11),
      message(4, "第二轮回答", 11),
    ],
    null,
    [run(10, "t1"), run(11, "t1")],
  );
  // 模拟第二轮提交时把用户消息回填进 extraMessages（与最近页重复）
  const thread = composeThread(
    recent,
    [],
    new Map(),
    [message(3, "第二轮问题", 11)],
  );
  expect(thread.items.map((item) => item.id)).toEqual([1, 2, 3, 4]);
  expect(thread.items.map((item) => item.content)).toEqual([
    "第一轮问题",
    "第一轮回答",
    "第二轮问题",
    "第二轮回答",
  ]);
});
