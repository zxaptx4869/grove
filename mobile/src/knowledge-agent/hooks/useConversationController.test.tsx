import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppState, type AppStateStatus } from "react-native";

import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import { useConversationController } from "@/src/knowledge-agent/hooks/useConversationController";
import type {
  KnowledgeConversation,
  KnowledgeMessage,
  KnowledgeRun,
} from "@/src/knowledge-agent/types";

jest.mock("expo-crypto", () => ({
  randomUUID: () => "test-client-id",
}));

jest.mock("@/src/knowledge-agent/api", () => ({
  knowledgeAgentApi: {
    listConversations: jest.fn(),
    createConversation: jest.fn(),
    getConversation: jest.fn(),
    changeScope: jest.fn(),
    listMessages: jest.fn(),
    submitMessage: jest.fn(),
    getRun: jest.fn(),
    cancelRun: jest.fn(),
  },
}));

const api = knowledgeAgentApi as jest.Mocked<typeof knowledgeAgentApi>;

const queryClients: QueryClient[] = [];

afterEach(() => {
  for (const client of queryClients) {
    client.clear();
  }
  queryClients.length = 0;
});

function conversation(id: number, overrides: Partial<KnowledgeConversation> = {}): KnowledgeConversation {
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
    lastActivityAt: "2026-08-29T10:00:00Z",
    createdAt: "2026-08-29T09:00:00Z",
    ...overrides,
  };
}

function message(
  id: number,
  role: "user" | "assistant",
  runId: number | null,
  content = "",
): KnowledgeMessage {
  return {
    id,
    conversationId: 1,
    role,
    messageType: role,
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
    createdAt: new Date(id * 1000).toISOString(),
  };
}

function run(
  id: number,
  status: KnowledgeRun["status"],
  updatedAt = "2026-08-29T10:00:00Z",
): KnowledgeRun {
  return {
    id,
    conversationId: 1,
    status,
    currentStep: status === "processing" ? "search" : null,
    scopeType: "workspace",
    projectId: null,
    projectName: null,
    userMessageId: 1,
    assistantMessageId: 2,
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

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  queryClients.push(queryClient);
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

async function renderController() {
  const wrapper = makeWrapper();
  return renderHook(() => useConversationController("token"), {
    wrapper,
  });
}

describe("useConversationController", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("draft 首次发送懒创建对话并重置一次性模式", async () => {
    api.listConversations.mockResolvedValue([]);
    api.createConversation.mockResolvedValue(conversation(10));
    api.getConversation.mockResolvedValue(conversation(10));
    api.submitMessage.mockResolvedValue({
      userMessage: message(11, "user", 5, "问题内容"),
      run: run(5, "waiting"),
    });
    api.listMessages.mockResolvedValue({ items: [], nextCursor: null, runs: [] });

    const rendered = await renderController();
    await waitFor(() => expect(rendered.result.current.initialLoading).toBe(false));

    await act(async () => {
      rendered.result.current.setContextMode("continue");
    });
    await act(async () => {
      rendered.result.current.setAnswerMode("investigate");
    });
    await act(async () => {
      await rendered.result.current.submit("  问题内容  ");
    });

    expect(api.createConversation).toHaveBeenCalledWith("token", {
      scopeType: "workspace",
      projectId: null,
    });
    expect(api.submitMessage).toHaveBeenCalledWith("token", 10, {
      clientMessageId: "test-client-id",
      message: "问题内容",
      contextMode: "continue",
      answerMode: "investigate",
    });
    expect(rendered.result.current.pending).toBeNull();
    expect(rendered.result.current.modes).toEqual({
      contextMode: "auto",
      answerMode: "auto",
    });
    await rendered.unmount();
  });

  test("提交超时后重试复用同一 conversation_id 与 client_message_id", async () => {
    api.listConversations.mockResolvedValue([]);
    api.createConversation.mockResolvedValue(conversation(20));
    api.getConversation.mockResolvedValue(conversation(20));
    api.submitMessage
      .mockRejectedValueOnce(new TypeError("Network request failed"))
      .mockResolvedValueOnce({
        userMessage: message(21, "user", 6, "问题"),
        run: run(6, "waiting"),
      });
    api.listMessages.mockResolvedValue({ items: [], nextCursor: null, runs: [] });

    const rendered = await renderController();
    await waitFor(() => expect(rendered.result.current.initialLoading).toBe(false));
    await act(async () => {
      await rendered.result.current.submit("问题");
    });

    expect(rendered.result.current.pending?.conversationId).toBe(20);
    expect(rendered.result.current.pending?.clientMessageId).toBe("test-client-id");
    expect(rendered.result.current.submitError).not.toBeNull();

    await act(async () => {
      await rendered.result.current.retrySubmit();
    });
    expect(api.createConversation).toHaveBeenCalledTimes(1);
    expect(api.submitMessage).toHaveBeenCalledTimes(2);
    const firstCall = api.submitMessage.mock.calls[0];
    const retryCall = api.submitMessage.mock.calls[1];
    expect(retryCall[1]).toBe(20);
    expect(retryCall[2].clientMessageId).toBe(firstCall[2].clientMessageId);
    expect(rendered.result.current.pending).toBeNull();
    await rendered.unmount();
  });

  test("已有对话时直接发送不创建新对话，连续追问进入同一对话", async () => {
    api.listConversations.mockResolvedValue([conversation(1)]);
    api.getConversation.mockResolvedValue(conversation(1));
    api.listMessages.mockResolvedValue({ items: [], nextCursor: null, runs: [] });
    api.submitMessage.mockResolvedValue({
      userMessage: message(3, "user", 2, "第二轮问题"),
      run: run(2, "waiting"),
    });

    const rendered = await renderController();
    await waitFor(() => expect(rendered.result.current.isDraft).toBe(false));
    await act(async () => {
      await rendered.result.current.submit("第二轮问题");
    });

    // 直接提交到已恢复的对话，不得再创建 Conversation
    expect(api.createConversation).not.toHaveBeenCalled();
    expect(api.submitMessage).toHaveBeenCalledWith("token", 1, {
      clientMessageId: "test-client-id",
      message: "第二轮问题",
      contextMode: "auto",
      answerMode: "auto",
    });
    expect(rendered.result.current.isDraft).toBe(false);
    await rendered.unmount();
  });

  test("活动 Run 409 时不创建第二个本地任务，只刷新服务端状态", async () => {
    api.listConversations.mockResolvedValue([]);
    api.createConversation.mockResolvedValue(conversation(30));
    api.submitMessage.mockRejectedValue({ status: 409, message: "进行中" });
    api.listMessages.mockResolvedValue({ items: [], nextCursor: null, runs: [] });
    api.getConversation.mockResolvedValue(conversation(30));

    const rendered = await renderController();
    await waitFor(() => expect(rendered.result.current.initialLoading).toBe(false));
    await act(async () => {
      await rendered.result.current.submit("问题");
    });

    expect(api.submitMessage).toHaveBeenCalledTimes(1);
    expect(rendered.result.current.pending?.phase).toBe("conflict");
    // 刷新服务端最近 Run：对话与消息被重新获取
    await waitFor(() => {
      expect(api.getConversation).toHaveBeenCalled();
      expect(api.listMessages).toHaveBeenCalled();
    });
    await rendered.unmount();
  });

  test("活动 Run 前台轮询并在终态停止", async () => {
    jest.useFakeTimers();
    const restoreAppState = mockAppStateActive();
    try {
      api.listConversations.mockResolvedValue([conversation(1)]);
      api.getConversation.mockResolvedValue(conversation(1));
      api.listMessages.mockResolvedValue({
        items: [
          message(1, "user", 7, "问题"),
          message(2, "assistant", 7),
        ],
        nextCursor: null,
        runs: [run(7, "processing")],
      });
      api.getRun
        .mockResolvedValueOnce(run(7, "processing"))
        .mockResolvedValueOnce(run(7, "completed"));

      const rendered = await renderController();
      await waitFor(() => expect(rendered.result.current.activeRun).not.toBeNull());
      await waitFor(() => {
        expect(api.getRun).toHaveBeenCalledWith("token", 7);
      });
      expect(rendered.result.current.runPolling).toBe(true);

      await act(async () => {
        jest.advanceTimersByTime(2500);
      });
      await waitFor(() => {
        expect(api.getRun).toHaveBeenCalledTimes(2);
      });
      await waitFor(() => {
        expect(rendered.result.current.runPolling).toBe(false);
      });
      await rendered.unmount();
    } finally {
      restoreAppState();
      jest.useRealTimers();
    }
  });

  test("进入后台停止轮询，回到前台恢复", async () => {
    jest.useFakeTimers();
    let appStateHandler: ((state: AppStateStatus) => void) | null = null;
    const originalState = AppState.currentState;
    Object.defineProperty(AppState, "currentState", {
      value: "active",
      configurable: true,
      writable: true,
    });
    const spy = jest
      .spyOn(AppState, "addEventListener")
      .mockImplementation(((type: string, handler: (state: AppStateStatus) => void) => {
        appStateHandler = handler;
        return { remove: jest.fn() } as never;
      }) as never);
    try {
      api.listConversations.mockResolvedValue([conversation(1)]);
      api.getConversation.mockResolvedValue(conversation(1));
      api.listMessages.mockResolvedValue({
        items: [message(1, "user", 8, "问题"), message(2, "assistant", 8)],
        nextCursor: null,
        runs: [run(8, "processing")],
      });
      api.getRun.mockResolvedValue(run(8, "processing"));

      const rendered = await renderController();
      await waitFor(() => expect(rendered.result.current.activeRun).not.toBeNull());
      const callsAfterForeground = api.getRun.mock.calls.length;

      await act(async () => {
        appStateHandler?.("background");
      });
      await act(async () => {
        jest.advanceTimersByTime(4500);
      });
      expect(api.getRun.mock.calls.length).toBe(callsAfterForeground);

      await act(async () => {
        appStateHandler?.("active");
      });
      await waitFor(() => {
        expect(api.getRun.mock.calls.length).toBeGreaterThan(callsAfterForeground);
      });
      await rendered.unmount();
    } finally {
      spy.mockRestore();
      Object.defineProperty(AppState, "currentState", {
        value: originalState,
        configurable: true,
        writable: true,
      });
      jest.useRealTimers();
    }
  });

  test("取消活动 Run 提交取消并保持轮询", async () => {
    const restoreAppState = mockAppStateActive();
    api.listConversations.mockResolvedValue([conversation(1)]);
    api.getConversation.mockResolvedValue(conversation(1));
    api.listMessages.mockResolvedValue({
      items: [message(1, "user", 9, "问题"), message(2, "assistant", 9)],
      nextCursor: null,
      runs: [run(9, "processing")],
    });
    api.getRun.mockResolvedValue(run(9, "processing"));
    api.cancelRun.mockResolvedValue({ ...run(9, "processing"), cancelRequested: true });

    const rendered = await renderController();
    await waitFor(() => expect(rendered.result.current.activeRun).not.toBeNull());
    await act(async () => {
      rendered.result.current.requestCancelRun();
    });
    await waitFor(() => {
      expect(api.cancelRun).toHaveBeenCalledWith("token", 9);
    });
    restoreAppState();
    await rendered.unmount();
  });
});

function mockAppStateActive() {
  const originalState = AppState.currentState;
  Object.defineProperty(AppState, "currentState", {
    value: "active",
    configurable: true,
    writable: true,
  });
  const listener = jest
    .spyOn(AppState, "addEventListener")
    .mockImplementation((() => ({ remove: jest.fn() })) as never);
  return () => {
    Object.defineProperty(AppState, "currentState", {
      value: originalState,
      configurable: true,
      writable: true,
    });
    listener.mockRestore();
  };
}
