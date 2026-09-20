import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import { useConversationController } from "@/src/knowledge-agent/hooks/useConversationController";
import {
  createPendingSubmission,
  type PendingSubmission,
} from "@/src/knowledge-agent/state/submission";
import type {
  KnowledgeConversation,
  KnowledgeMessage,
  KnowledgeMessagePage,
  KnowledgeRun,
} from "@/src/knowledge-agent/types";

let mockAppActive = true;
const mockExitRecovery = jest.fn();
interface MockSessionSeed {
  choice: number | "draft";
  scope: { scopeType: "workspace" | "project"; projectId: number | null; projectName?: string };
  input: string;
  pending: PendingSubmission | null;
  pendingState: "in_flight" | "result_unknown" | "creation_unknown" | null;
  recoveryRun: { conversationId: number; runId: number } | null;
  bootStatus: "idle" | "loading" | "ready" | "error";
  bootError: string | null;
  persistenceError: string | null;
}

let mockSessionInitial: MockSessionSeed = {
  choice: 1 as number | "draft",
  scope: { scopeType: "workspace" as const, projectId: null },
  input: "",
  pending: null,
  pendingState: null,
  recoveryRun: null,
  bootStatus: "ready" as const,
  bootError: null,
  persistenceError: null,
};

jest.mock("@/src/knowledge-agent/hooks/useAppState", () => ({
  useAppStateActive: () => mockAppActive,
}));

jest.mock("@/src/knowledge-agent/session/DialogueSessionProvider", () => {
  const ReactModule = jest.requireActual<typeof import("react")>("react");
  return {
    useDialogueSession: () => {
      const [state, setState] = ReactModule.useState(() => ({ ...mockSessionInitial }));
      return {
        ...state,
        update: (patch: Partial<MockSessionSeed>) =>
          setState((previous) => ({ ...previous, ...patch })),
        retryBootstrap: jest.fn(),
        retryPersistence: jest.fn(),
        exitRecovery: async () => {
          mockExitRecovery();
          setState((previous) => ({
            ...mockSessionInitial,
            scope: previous.scope,
            choice: "draft",
            input: "",
            pending: null,
            pendingState: null,
            recoveryRun: null,
            bootStatus: "ready",
            bootError: null,
            persistenceError: null,
          }));
        },
        getReadingPosition: jest.fn(() => null),
        setReadingPosition: jest.fn(),
        clearReadingPosition: jest.fn(),
      };
    },
  };
});

jest.mock("expo-crypto", () => ({
  randomUUID: jest.fn(() => "new-client-id"),
}));

jest.mock("@/src/knowledge-agent/api", () => ({
  knowledgeAgentApi: {
    listConversations: jest.fn(),
    createConversation: jest.fn(),
    getConversation: jest.fn(),
    changeScope: jest.fn(),
    listMessages: jest.fn(),
    submitMessage: jest.fn(),
    getEntryCurrent: jest.fn(),
    getRun: jest.fn(),
    cancelRun: jest.fn(),
  },
}));

const api = knowledgeAgentApi as jest.Mocked<typeof knowledgeAgentApi>;
const clients: QueryClient[] = [];
const unmounts: (() => Promise<void>)[] = [];

afterEach(async () => {
  await act(async () => {
    await Promise.all(unmounts.map((unmount) => unmount()));
    await new Promise((resolve) => setTimeout(resolve, 0));
    await Promise.all(clients.map((client) => client.cancelQueries()));
  });
  unmounts.length = 0;
  clients.forEach((client) => client.clear());
  clients.length = 0;
  jest.clearAllMocks();
  mockAppActive = true;
  mockSessionInitial = {
    choice: 1,
    scope: { scopeType: "workspace", projectId: null },
    input: "",
    pending: null,
    pendingState: null,
    recoveryRun: null,
    bootStatus: "ready",
    bootError: null,
    persistenceError: null,
  };
});

function conversation(id: number): KnowledgeConversation {
  return {
    id,
    title: `对话 ${id}`,
    scopeType: "workspace",
    projectId: null,
    projectName: null,
    activeTopicLabel: null,
    activeContextVersionId: null,
    activeEntryCount: 0,
    recentRunId: null,
    recentRunStatus: null,
    recentRunCurrentStep: null,
    recentRunUpdatedAt: null,
    lastActivityAt: `2026-09-19T10:0${id}:00Z`,
    createdAt: "2026-09-19T09:00:00Z",
  };
}

function message(
  id: number,
  role: "user" | "assistant",
  runId: number,
  conversationId = 1,
  content = "问题",
): KnowledgeMessage {
  return {
    id,
    conversationId,
    role,
    messageType: role,
    content,
    clientMessageId: null,
    runId,
    scopeType: "workspace",
    projectId: null,
    projectName: null,
    requestContextMode: "auto",
    contextDecision: null,
    standaloneQuery: null,
    topicLabel: null,
    createdAt: new Date(id * 1000).toISOString(),
  };
}

function run(
  id: number,
  status: KnowledgeRun["status"],
  conversationId = 1,
  overrides: Partial<KnowledgeRun> = {},
): KnowledgeRun {
  return {
    id,
    conversationId,
    status,
    currentStep: status === "processing" ? "dialogue_loop" : null,
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
    dialogueStage: status === "processing" ? "querying" : null,
    dialogueBlocks: [],
    canContinue: false,
    continuation: null,
    createdAt: "2026-09-19T10:00:00Z",
    updatedAt: "2026-09-19T10:00:00Z",
    ...overrides,
  };
}

function page(
  items: KnowledgeMessage[] = [],
  runs: KnowledgeRun[] = [],
  nextCursor: string | null = null,
): KnowledgeMessagePage {
  return { items, runs, nextCursor };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

async function setup(
  conversations: KnowledgeConversation[] = [conversation(1)],
  pages: Record<number, KnowledgeMessagePage> = { 1: page() },
  runLoader?: (runId: number) => Promise<KnowledgeRun>,
  conversationLoader?: (conversationId: number) => Promise<KnowledgeConversation>,
) {
  api.listConversations.mockResolvedValue(conversations);
  api.getConversation.mockImplementation(
    async (_token, id) =>
      conversationLoader
        ? conversationLoader(id)
        : conversations.find((item) => item.id === id) ?? conversation(id),
  );
  api.listMessages.mockImplementation(async (_token, id) => pages[id] ?? page());
  api.getRun.mockImplementation(async (_token, id) => {
    if (runLoader) return runLoader(id);
    for (const value of Object.values(pages)) {
      const existing = value.runs.find((item) => item.id === id);
      if (existing) return existing;
    }
    return run(id, "completed");
  });
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false, gcTime: Infinity },
    },
  });
  clients.push(client);
  const rendered = await renderHook(() => useConversationController("token"), {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
  unmounts.push(rendered.unmount);
  return rendered;
}

test("continuation 绑定当前 Run 并以新正式消息提交", async () => {
  const sourceRun = run(10, "partial", 1, {
    dialogueLoopStatus: "partial_completed",
    canContinue: true,
  });
  const rendered = await setup([conversation(1)], {
    1: page([message(1, "user", 10), message(2, "assistant", 10, 1, "部分结果")], [sourceRun]),
  });
  api.submitMessage.mockResolvedValue({
    userMessage: message(3, "user", 11, 1, "继续"),
    run: run(11, "waiting"),
  });
  await waitFor(() => expect(rendered.result.current.thread.runsById.get(10)).toBeDefined());
  await act(async () => {
    expect(await rendered.result.current.continueRun(10)).toBe(true);
  });
  expect(api.submitMessage).toHaveBeenCalledWith("token", 1, {
    clientMessageId: "new-client-id",
    message: "继续",
    contextMode: "auto",
  });
});

test("旧历史 Run 即使残留 can_continue 也不能续接当前任务", async () => {
  const older = run(9, "partial", 1, {
    dialogueLoopStatus: "partial_completed",
    canContinue: true,
    updatedAt: "2026-09-19T09:00:00Z",
  });
  const current = run(10, "completed", 1, {
    canContinue: false,
    updatedAt: "2026-09-19T10:00:00Z",
  });
  const currentConversation = { ...conversation(1), recentRunId: 10 };
  const rendered = await setup([currentConversation], {
    1: page(
      [
        message(1, "user", 9),
        message(2, "assistant", 9, 1, "旧的部分结果"),
        message(3, "user", 10, 1, "新问题"),
        message(4, "assistant", 10, 1, "新回答"),
      ],
      [older, current],
    ),
  });
  await waitFor(() => expect(rendered.result.current.thread.runsById.get(9)).toBeDefined());
  expect(rendered.result.current.resumableRunId).toBeNull();
  await act(async () => {
    expect(await rendered.result.current.continueRun(9)).toBe(false);
  });
  expect(api.submitMessage).not.toHaveBeenCalled();
});

test("提交结果未知重试复用同一幂等键", async () => {
  const rendered = await setup();
  api.submitMessage
    .mockRejectedValueOnce(new TypeError("Network request failed"))
    .mockResolvedValueOnce({
      userMessage: message(3, "user", 12, 1, "普通问题"),
      run: run(12, "waiting"),
    });
  await waitFor(() => expect(rendered.result.current.activeConversation?.id).toBe(1));
  await act(async () => {
    expect(await rendered.result.current.submit("普通问题")).toBe(false);
  });
  const stableId = rendered.result.current.pending?.clientMessageId;
  expect(stableId).toBe("new-client-id");
  expect(rendered.result.current.submitting).toBe(false);
  expect(rendered.result.current.submissionResultUnknown).toBe(true);
  await act(async () => {
    expect(await rendered.result.current.retrySubmit()).toBe(true);
  });
  expect(api.submitMessage).toHaveBeenCalledTimes(2);
  expect(api.submitMessage.mock.calls[0][2].clientMessageId).toBe(stableId);
  expect(api.submitMessage.mock.calls[1][2].clientMessageId).toBe(stableId);
  expect(rendered.result.current.submissionResultUnknown).toBe(false);
});

test("无待恢复工作时默认空白新对话，首次发送才创建 Conversation", async () => {
  mockSessionInitial = { ...mockSessionInitial, choice: "draft" };
  const rendered = await setup();
  await waitFor(() => expect(rendered.result.current.initialLoading).toBe(false));
  expect(rendered.result.current.isDraft).toBe(true);
  expect(rendered.result.current.activeConversation).toBeNull();
  expect(api.createConversation).not.toHaveBeenCalled();

  api.createConversation.mockResolvedValue(conversation(9));
  api.submitMessage.mockResolvedValue({
    userMessage: message(9, "user", 90, 9, "首次问题"),
    run: run(90, "waiting", 9),
  });
  await act(async () => {
    expect(await rendered.result.current.submit("首次问题")).toBe(true);
  });
  expect(api.createConversation).toHaveBeenCalledTimes(1);
  expect(api.submitMessage).toHaveBeenCalledWith(
    "token",
    9,
    expect.objectContaining({ message: "首次问题" }),
  );
});

test("本地恢复失败时从历史新建会话可退出错误态", async () => {
  mockSessionInitial = {
    ...mockSessionInitial,
    choice: "draft",
    bootStatus: "error",
    bootError: "恢复记录读取失败",
  };
  const rendered = await setup();
  expect(rendered.result.current.recoveryError).toBe("恢复记录读取失败");

  await act(async () => {
    rendered.result.current.startNewConversation();
    await Promise.resolve();
  });

  await waitFor(() => expect(rendered.result.current.recoveryError).toBeNull());
  expect(mockExitRecovery).toHaveBeenCalledTimes(1);
  expect(rendered.result.current.isDraft).toBe(true);
});

test("创建 Conversation 结果未知时不自动重建或提交消息", async () => {
  mockSessionInitial = { ...mockSessionInitial, choice: "draft" };
  const rendered = await setup();
  api.createConversation.mockRejectedValueOnce(new TypeError("Network request failed"));

  await act(async () => {
    expect(await rendered.result.current.submit("不能重建的问题")).toBe(false);
  });
  expect(rendered.result.current.conversationCreationUnknown).toBe(true);
  expect(rendered.result.current.pending?.clientMessageId).toBe("new-client-id");
  expect(await rendered.result.current.retrySubmit()).toBe(false);
  expect(api.createConversation).toHaveBeenCalledTimes(1);
  expect(api.submitMessage).not.toHaveBeenCalled();
});

test("恢复时先用 client_message_id 对账，已存在则不重复提交", async () => {
  const pending = {
    ...createPendingSubmission({ text: "已到达问题", contextMode: "auto" }),
    clientMessageId: "stable-client-id",
    conversationId: 1,
  };
  mockSessionInitial = {
    ...mockSessionInitial,
    choice: 1,
    input: "已到达问题",
    pending,
    pendingState: "result_unknown",
  };
  const confirmed = {
    ...message(3, "user", 12, 1, "已到达问题"),
    clientMessageId: "stable-client-id",
  };
  const rendered = await setup([conversation(1)], {
    1: page([confirmed], [run(12, "completed")]),
  });

  await waitFor(() => expect(rendered.result.current.pending).toBeNull());
  expect(rendered.result.current.submissionResultUnknown).toBe(false);
  expect(api.submitMessage).not.toHaveBeenCalled();
});

test("服务端恢复失败时保留明确错误并可重试", async () => {
  mockSessionInitial = { ...mockSessionInitial, input: "待恢复输入" };
  let shouldFail = true;
  const rendered = await setup(
    [conversation(1)],
    { 1: page() },
    undefined,
    async (id) => {
      if (shouldFail) throw new TypeError("Network request failed");
      return conversation(id);
    },
  );
  await waitFor(() => expect(rendered.result.current.recoveryError).not.toBeNull());

  shouldFail = false;
  await act(async () => {
    rendered.result.current.retryRecovery();
  });
  await waitFor(() => expect(rendered.result.current.activeConversation?.id).toBe(1));
  expect(rendered.result.current.recoveryError).toBeNull();
});

test("离开期间完成的活动 Run 恢复终态结果", async () => {
  mockSessionInitial = {
    ...mockSessionInitial,
    recoveryRun: { conversationId: 1, runId: 10 },
  };
  const processing = run(10, "processing");
  const completed = run(10, "completed", 1, {
    dialogueBlocks: [{ kind: "text", text: "离开期间已完成" }],
    updatedAt: "2026-09-20T10:05:00Z",
  });
  const rendered = await setup(
    [conversation(1)],
    {
      1: page(
        [message(1, "user", 10), message(2, "assistant", 10, 1, "")],
        [processing],
      ),
    },
    async () => completed,
  );

  await waitFor(() =>
    expect(rendered.result.current.thread.runsById.get(10)?.status).toBe("completed"),
  );
  expect(rendered.result.current.activeRun).toBeNull();
  expect(api.getRun).toHaveBeenCalledWith("token", 10);
});

test("正常提交进行中不能重复发送或恢复，且不进入结果未知", async () => {
  const submission = deferred<{
    userMessage: KnowledgeMessage;
    run: KnowledgeRun;
  }>();
  const rendered = await setup();
  api.submitMessage.mockReturnValue(submission.promise);
  await waitFor(() => expect(rendered.result.current.activeConversation?.id).toBe(1));

  let request!: Promise<boolean>;
  await act(async () => {
    request = rendered.result.current.submit("普通问题");
    await Promise.resolve();
  });
  await waitFor(() => expect(rendered.result.current.submitting).toBe(true));
  expect(rendered.result.current.submissionResultUnknown).toBe(false);
  expect(await rendered.result.current.submit("重复问题")).toBe(false);
  expect(await rendered.result.current.retrySubmit()).toBe(false);
  expect(api.submitMessage).toHaveBeenCalledTimes(1);

  submission.resolve({
    userMessage: message(3, "user", 12, 1, "普通问题"),
    run: run(12, "waiting"),
  });
  await act(async () => {
    expect(await request).toBe(true);
  });
  expect(rendered.result.current.submitting).toBe(false);
  expect(rendered.result.current.pending).toBeNull();
});

test("409 与明确服务端失败不伪装成提交结果未知", async () => {
  const rendered = await setup();
  await waitFor(() => expect(rendered.result.current.activeConversation?.id).toBe(1));

  api.submitMessage.mockRejectedValueOnce(
    Object.assign(new Error("已有进行中的回答"), { status: 409 }),
  );
  await act(async () => {
    expect(await rendered.result.current.submit("冲突问题")).toBe(false);
  });
  expect(rendered.result.current.pending).toBeNull();
  expect(rendered.result.current.submissionResultUnknown).toBe(false);
  expect(rendered.result.current.submitError).toContain("已有进行中的回答");

  api.submitMessage.mockRejectedValueOnce(
    Object.assign(new Error("服务暂时不可用"), { status: 503 }),
  );
  await act(async () => {
    expect(await rendered.result.current.submit("服务失败问题")).toBe(false);
  });
  expect(rendered.result.current.pending).toBeNull();
  expect(rendered.result.current.submissionResultUnknown).toBe(false);
  expect(rendered.result.current.submitError).toBe("服务暂时不可用");
});

test("切换会话后只恢复目标 Conversation 的服务端消息", async () => {
  const rendered = await setup([conversation(1), conversation(2)], {
    1: page([message(1, "user", 10, 1, "会话一")]),
    2: page([message(5, "user", 20, 2, "会话二")]),
  });
  await waitFor(() => expect(rendered.result.current.thread.items[0]?.content).toBe("会话一"));
  await act(async () => {
    rendered.result.current.switchToConversation(2);
  });
  await waitFor(() => expect(rendered.result.current.activeConversation?.id).toBe(2));
  await waitFor(() => expect(rendered.result.current.thread.items[0]?.content).toBe("会话二"));
});

test("会话 A 的迟到历史页成功响应不污染会话 B", async () => {
  const older = deferred<KnowledgeMessagePage>();
  const pages: Record<number, KnowledgeMessagePage> = {
    1: page([message(5, "user", 15, 1, "会话一最近消息")], [], "a-older"),
    2: page([message(20, "user", 20, 2, "会话二消息")], [], "b-older"),
  };
  const rendered = await setup([conversation(1), conversation(2)], pages);
  await waitFor(() => expect(rendered.result.current.thread.nextCursor).toBe("a-older"));
  api.listMessages.mockImplementation(async (_token, id, cursor) => {
    if (id === 1 && cursor === "a-older") return older.promise;
    return pages[id] ?? page();
  });

  let request!: Promise<void>;
  await act(async () => {
    request = rendered.result.current.loadOlderMessages();
    await Promise.resolve();
  });
  await waitFor(() => expect(rendered.result.current.loadingOlder).toBe(true));
  await act(async () => {
    rendered.result.current.switchToConversation(2);
  });
  await waitFor(() => expect(rendered.result.current.activeConversation?.id).toBe(2));
  await waitFor(() => expect(rendered.result.current.thread.items[0]?.id).toBe(20));

  older.resolve(
    page(
      [message(3, "user", 13, 1, "会话一旧消息")],
      [run(13, "completed", 1)],
      null,
    ),
  );
  await act(async () => {
    await request;
  });

  expect(rendered.result.current.thread.items.map((item) => item.id)).toEqual([20]);
  expect(rendered.result.current.thread.runsById.has(13)).toBe(false);
  expect(rendered.result.current.thread.nextCursor).toBe("b-older");
  expect(rendered.result.current.loadingOlder).toBe(false);
  expect(rendered.result.current.olderError).toBeNull();
});

test("会话 A 的迟到历史页失败不污染新对话", async () => {
  const older = deferred<KnowledgeMessagePage>();
  const rendered = await setup([conversation(1)], {
    1: page([message(5, "user", 15)], [], "a-older"),
  });
  await waitFor(() => expect(rendered.result.current.thread.nextCursor).toBe("a-older"));
  api.listMessages.mockImplementation(async (_token, id, cursor) => {
    if (id === 1 && cursor === "a-older") return older.promise;
    return page();
  });

  let request!: Promise<void>;
  await act(async () => {
    request = rendered.result.current.loadOlderMessages();
    await Promise.resolve();
  });
  await waitFor(() => expect(rendered.result.current.loadingOlder).toBe(true));
  await act(async () => {
    rendered.result.current.startNewConversation();
  });
  await waitFor(() => expect(rendered.result.current.isDraft).toBe(true));

  older.reject(new TypeError("Network request failed"));
  await act(async () => {
    await request;
  });

  expect(rendered.result.current.thread.items).toEqual([]);
  expect(rendered.result.current.loadingOlder).toBe(false);
  expect(rendered.result.current.olderError).toBeNull();
});

test("会话 A 的迟到范围失败不改变会话 B 状态", async () => {
  const scope = deferred<KnowledgeConversation>();
  const rendered = await setup([conversation(1), conversation(2)], {
    1: page([message(1, "user", 10, 1, "会话一")]),
    2: page([message(5, "user", 20, 2, "会话二")]),
  });
  api.changeScope.mockReturnValue(scope.promise);
  await waitFor(() => expect(rendered.result.current.activeConversation?.id).toBe(1));

  let request!: Promise<void>;
  await act(async () => {
    request = rendered.result.current.changeScope({ scopeType: "project", projectId: 8 });
    await Promise.resolve();
  });
  await waitFor(() => expect(rendered.result.current.scopeBusy).toBe(true));
  await act(async () => {
    rendered.result.current.switchToConversation(2);
  });
  await waitFor(() => expect(rendered.result.current.activeConversation?.id).toBe(2));
  expect(rendered.result.current.scopeBusy).toBe(false);

  scope.reject(new TypeError("Network request failed"));
  await act(async () => {
    await request;
  });

  expect(rendered.result.current.activeConversation?.id).toBe(2);
  expect(rendered.result.current.scopeError).toBeNull();
  expect(rendered.result.current.thread.items.map((item) => item.id)).toEqual([5]);
});

test("会话 A 的迟到范围成功不清空会话 B 已加载历史", async () => {
  const scope = deferred<KnowledgeConversation>();
  const recentPages: Record<number, KnowledgeMessagePage> = {
    1: page([message(1, "user", 10, 1, "会话一")]),
    2: page([message(6, "assistant", 20, 2, "会话二最近消息")], [], "b-older"),
  };
  const rendered = await setup([conversation(1), conversation(2)], recentPages);
  api.changeScope.mockReturnValue(scope.promise);
  await waitFor(() => expect(rendered.result.current.activeConversation?.id).toBe(1));

  let scopeRequest!: Promise<void>;
  await act(async () => {
    scopeRequest = rendered.result.current.changeScope({
      scopeType: "project",
      projectId: 8,
    });
    await Promise.resolve();
  });
  await act(async () => {
    rendered.result.current.switchToConversation(2);
  });
  await waitFor(() => expect(rendered.result.current.thread.nextCursor).toBe("b-older"));
  api.listMessages.mockImplementation(async (_token, id, cursor) => {
    if (id === 2 && cursor === "b-older") {
      return page(
        [message(4, "assistant", 19, 2, "会话二旧消息")],
        [run(19, "completed", 2)],
        null,
      );
    }
    return recentPages[id] ?? page();
  });
  await act(async () => {
    await rendered.result.current.loadOlderMessages();
  });
  await waitFor(() =>
    expect(rendered.result.current.thread.items.map((item) => item.id)).toEqual([4, 6]),
  );

  scope.resolve({
    ...conversation(1),
    scopeType: "project",
    projectId: 8,
    projectName: "会话一项目",
  });
  await act(async () => {
    await scopeRequest;
  });

  expect(rendered.result.current.activeConversation?.id).toBe(2);
  expect(rendered.result.current.thread.items.map((item) => item.id)).toEqual([4, 6]);
  expect(rendered.result.current.thread.runsById.has(19)).toBe(true);
  expect(rendered.result.current.thread.hasMore).toBe(false);
});

test("会话 A 的迟到取消成功不改变会话 B 的活动 Run", async () => {
  mockAppActive = false;
  const cancellation = deferred<KnowledgeRun>();
  const runA = run(10, "processing", 1);
  const runB = run(20, "processing", 2);
  const rendered = await setup([conversation(1), conversation(2)], {
    1: page([message(1, "user", 10, 1), message(2, "assistant", 10, 1)], [runA]),
    2: page([message(5, "user", 20, 2), message(6, "assistant", 20, 2)], [runB]),
  });
  api.cancelRun.mockReturnValue(cancellation.promise);
  await waitFor(() => expect(rendered.result.current.activeRun?.id).toBe(10));

  let request!: Promise<void>;
  await act(async () => {
    request = rendered.result.current.requestCancelRun();
    await Promise.resolve();
  });
  await waitFor(() => expect(rendered.result.current.cancelling).toBe(true));
  await act(async () => {
    rendered.result.current.switchToConversation(2);
  });
  await waitFor(() => expect(rendered.result.current.activeRun?.id).toBe(20));
  expect(rendered.result.current.cancelling).toBe(false);

  cancellation.resolve(
    run(10, "cancelled", 1, { updatedAt: "2026-09-19T10:01:00Z" }),
  );
  await act(async () => {
    await request;
  });

  expect(rendered.result.current.activeRun?.id).toBe(20);
  expect(rendered.result.current.thread.runsById.has(10)).toBe(false);
  expect(rendered.result.current.cancelError).toBeNull();
});

test("App 在后台时不轮询，恢复前台后读取同一活动 Run", async () => {
  mockAppActive = false;
  const processing = run(10, "processing");
  const rendered = await setup(
    [conversation(1)],
    {
      1: page([message(1, "user", 10), message(2, "assistant", 10)], [processing]),
    },
    () => new Promise<KnowledgeRun>(() => undefined),
  );
  api.getRun.mockResolvedValue(run(10, "completed", 1, { dialogueBlocks: [{ kind: "text", text: "完成" }] }));
  await waitFor(() => expect(rendered.result.current.activeRun?.id).toBe(10));
  expect(api.getRun).not.toHaveBeenCalled();

  mockAppActive = true;
  await rendered.rerender(undefined);
  await waitFor(() => expect(api.getRun).toHaveBeenCalledWith("token", 10));
  await waitFor(() => expect(rendered.result.current.activeRun).toBeNull());
});

test("失败后重新提问创建新的 Run，不复用旧消息标识", async () => {
  const failed = run(10, "failed", 1, { error: "服务失败" });
  const rendered = await setup([conversation(1)], {
    1: page([message(1, "user", 10, 1, "原问题"), message(2, "assistant", 10)], [failed]),
  });
  api.submitMessage.mockResolvedValue({
    userMessage: message(3, "user", 11, 1, "原问题"),
    run: run(11, "waiting"),
  });
  await waitFor(() => expect(rendered.result.current.thread.runsById.get(10)).toBeDefined());
  await act(async () => {
    expect(await rendered.result.current.retryRun(10)).toBe(true);
  });
  expect(api.submitMessage.mock.calls[0][2]).toMatchObject({
    clientMessageId: "new-client-id",
    message: "原问题",
  });
});

test("取消只提交当前活动 Run", async () => {
  const processing = run(10, "processing");
  const rendered = await setup(
    [conversation(1)],
    {
      1: page([message(1, "user", 10), message(2, "assistant", 10)], [processing]),
    },
    () => new Promise<KnowledgeRun>(() => undefined),
  );
  const cancelled = run(10, "cancelled", 1, {
    updatedAt: "2026-09-19T10:01:00Z",
  });
  api.cancelRun.mockResolvedValue(cancelled);
  await waitFor(() => expect(rendered.result.current.activeRun?.id).toBe(10));
  await act(async () => {
    await rendered.result.current.requestCancelRun();
  });
  expect(api.cancelRun).toHaveBeenCalledWith("token", 10);
  await waitFor(() => expect(rendered.result.current.activeRun).toBeNull());
});
