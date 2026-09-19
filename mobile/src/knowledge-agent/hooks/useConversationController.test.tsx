import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import { useConversationController } from "@/src/knowledge-agent/hooks/useConversationController";
import type {
  KnowledgeConversation,
  KnowledgeMessage,
  KnowledgeMessagePage,
  KnowledgeRun,
} from "@/src/knowledge-agent/types";

let mockAppActive = true;

jest.mock("@/src/knowledge-agent/hooks/useAppState", () => ({
  useAppStateActive: () => mockAppActive,
}));

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
): KnowledgeMessagePage {
  return { items, runs, nextCursor: null };
}

async function setup(
  conversations: KnowledgeConversation[] = [conversation(1)],
  pages: Record<number, KnowledgeMessagePage> = { 1: page() },
  runLoader?: (runId: number) => Promise<KnowledgeRun>,
) {
  api.listConversations.mockResolvedValue(conversations);
  api.getConversation.mockImplementation(
    async (_token, id) => conversations.find((item) => item.id === id) ?? conversation(id),
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
  await act(async () => {
    expect(await rendered.result.current.retrySubmit()).toBe(true);
  });
  expect(api.submitMessage).toHaveBeenCalledTimes(2);
  expect(api.submitMessage.mock.calls[0][2].clientMessageId).toBe(stableId);
  expect(api.submitMessage.mock.calls[1][2].clientMessageId).toBe(stableId);
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
