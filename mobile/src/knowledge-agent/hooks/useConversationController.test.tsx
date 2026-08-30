import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppState, type AppStateStatus } from "react-native";

import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import { useConversationController } from "@/src/knowledge-agent/hooks/useConversationController";
import type {
  KnowledgeCandidateDraft,
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
    submitDraftAction: jest.fn(),
    getDraft: jest.fn(),
    editDraft: jest.fn(),
    cancelDraft: jest.fn(),
    confirmDraft: jest.fn(),
  },
}));

const api = knowledgeAgentApi as jest.Mocked<typeof knowledgeAgentApi>;

const queryClients: QueryClient[] = [];

afterEach(async () => {
  await act(async () => {
    await Promise.all(queryClients.map((client) => client.cancelQueries()));
  });
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
    runKind: "answer",
    sourceRunId: null,
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

function draft(
  id: number,
  overrides: Partial<KnowledgeCandidateDraft> = {},
): KnowledgeCandidateDraft {
  return {
    id,
    conversationId: 1,
    operationRunId: 10,
    sourceRunId: 5,
    targetProjectId: 1,
    targetProjectName: "新房装修",
    status: "generating",
    title: null,
    content: null,
    mainType: null,
    infoNature: null,
    evidenceHandles: [],
    evidenceSummaries: [],
    generationDegraded: false,
    generationError: null,
    confirmedCandidateId: null,
    error: null,
    createdAt: "2026-08-29T10:00:00Z",
    updatedAt: "2026-08-29T10:00:00Z",
    ...overrides,
  };
}

function answeredRun(
  id: number,
  status: "completed" | "partial",
): KnowledgeRun {
  return {
    ...run(id, status),
    runKind: "answer",
    scopeType: "project",
    projectId: 1,
    projectName: "新房装修",
    answer: {
      answer: "闭水试验通常持续 24 小时。",
      status,
      insufficientNote: null,
      citations: [
        {
          evidenceId: 11,
          evidenceHandle: "ev_1",
          entryId: 1,
          entryTitle: "闭水试验",
          sourceId: 1,
          sourceTitle: "验收手册",
          attachmentId: 1,
          quote: "闭水试验通常持续 24 小时",
          scopeType: "project",
          projectId: 1,
          projectName: "新房装修",
          nodePath: "施工",
        },
      ],
      conflicts: [],
    },
  };
}

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
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
    api.listMessages.mockResolvedValue({
      items: [],
      nextCursor: null,
      runs: [],
      candidateDrafts: [],
    });

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
    api.listMessages.mockResolvedValue({
      items: [],
      nextCursor: null,
      runs: [],
      candidateDrafts: [],
    });

    const rendered = await renderController();
    await waitFor(() => expect(rendered.result.current.initialLoading).toBe(false));
    let firstResult: boolean | undefined;
    await act(async () => {
      firstResult = await rendered.result.current.submit("问题");
    });

    expect(firstResult).toBe(false);
    expect(rendered.result.current.pending?.conversationId).toBe(20);
    expect(rendered.result.current.pending?.clientMessageId).toBe("test-client-id");
    expect(rendered.result.current.submitError).not.toBeNull();

    let retryResult: boolean | undefined;
    await act(async () => {
      retryResult = await rendered.result.current.retrySubmit();
    });
    expect(retryResult).toBe(true);
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
    api.listMessages.mockResolvedValue({
      items: [],
      nextCursor: null,
      runs: [],
      candidateDrafts: [],
    });
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
    api.listMessages.mockResolvedValue({
      items: [],
      nextCursor: null,
      runs: [],
      candidateDrafts: [],
    });
    api.getConversation.mockResolvedValue(conversation(30));

    const rendered = await renderController();
    await waitFor(() => expect(rendered.result.current.initialLoading).toBe(false));
    await act(async () => {
      await rendered.result.current.submit("问题");
    });

    expect(api.submitMessage).toHaveBeenCalledTimes(1);
    // 409 后不保留“发送中”气泡，错误文案说明冲突
    expect(rendered.result.current.pending).toBeNull();
    expect(rendered.result.current.submitError).toContain("进行中的回答");
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
        candidateDrafts: [],
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
      jest.clearAllTimers();
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
        candidateDrafts: [],
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
      jest.clearAllTimers();
      jest.useRealTimers();
    }
  });

  test("取消活动 Run 提交取消并保持轮询", async () => {
    jest.useFakeTimers();
    const restoreAppState = mockAppStateActive();
    try {
      api.listConversations.mockResolvedValue([conversation(1)]);
      api.getConversation.mockResolvedValue(conversation(1));
      api.listMessages.mockResolvedValue({
        items: [message(1, "user", 9, "问题"), message(2, "assistant", 9)],
        nextCursor: null,
        runs: [run(9, "processing")],
        candidateDrafts: [],
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
      await rendered.unmount();
    } finally {
      restoreAppState();
      jest.clearAllTimers();
      jest.useRealTimers();
    }
  });

  test("取消错误仅保留给原 Run，切换会话后清理", async () => {
    jest.useFakeTimers();
    const restoreAppState = mockAppStateActive();
    try {
      api.listConversations.mockResolvedValue([conversation(1), conversation(2)]);
      api.getConversation.mockResolvedValue(conversation(1));
      api.listMessages.mockResolvedValue({
        items: [message(1, "user", 9, "问题"), message(2, "assistant", 9)],
        nextCursor: null,
        runs: [run(9, "processing")],
        candidateDrafts: [],
      });
      api.getRun.mockResolvedValue(run(9, "processing"));
      api.cancelRun.mockRejectedValue(new Error("取消请求失败"));

      const rendered = await renderController();
      await waitFor(() => expect(rendered.result.current.activeRun?.id).toBe(9));
      await act(async () => {
        rendered.result.current.requestCancelRun();
      });
      await waitFor(() => {
        expect(rendered.result.current.cancelError).toContain("取消请求失败");
      });

      await act(async () => {
        rendered.result.current.switchToConversation(2);
      });
      expect(rendered.result.current.cancelError).toBeNull();
      await rendered.unmount();
    } finally {
      restoreAppState();
      jest.clearAllTimers();
      jest.useRealTimers();
    }
  });

  test("提交整理动作：可见消息、operation Run 与草稿进入线程", async () => {
    api.listConversations.mockResolvedValue([conversation(1)]);
    api.getConversation.mockResolvedValue(conversation(1));
    api.listMessages.mockResolvedValue({
      items: [
        message(1, "user", 9, "闭水试验通常持续多久？"),
        message(2, "assistant", 9),
      ],
      nextCursor: null,
      runs: [answeredRun(9, "completed")],
      candidateDrafts: [],
    });
    api.submitDraftAction.mockResolvedValue({
      userMessage: message(3, "user", 10, "整理成知识（目标项目：新房装修）"),
      run: { ...run(10, "waiting"), runKind: "draft_candidate", sourceRunId: 9 },
      draft: draft(1),
    });
    const rendered = await renderController();
    await waitFor(() =>
      expect(rendered.result.current.thread.runsById.get(9)?.status).toBe(
        "completed",
      ),
    );

    await act(async () => {
      const submitted = await rendered.result.current.submitDraftAction(9);
      expect(submitted).toBe(true);
    });

    await waitFor(() => {
      expect(rendered.result.current.draftsById.get(1)?.status).toBe(
        "generating",
      );
      expect(rendered.result.current.draftByRunId(10)?.id).toBe(1);
    });
    expect(
      rendered.result.current.thread.items.some(
        (item) => item.content === "整理成知识（目标项目：新房装修）",
      ),
    ).toBe(true);
    expect(api.submitDraftAction).toHaveBeenCalledWith(
      "token",
      1,
      expect.objectContaining({
        sourceRunId: 9,
        clientMessageId: "test-client-id",
      }),
    );
  });

  test("整理动作 409 冲突：显示错误且不保留重试状态", async () => {
    api.listConversations.mockResolvedValue([conversation(1)]);
    api.getConversation.mockResolvedValue(conversation(1));
    api.listMessages.mockResolvedValue({
      items: [message(1, "user", 9), message(2, "assistant", 9)],
      nextCursor: null,
      runs: [answeredRun(9, "completed")],
      candidateDrafts: [],
    });
    (api.submitDraftAction as jest.Mock).mockRejectedValueOnce({
      status: 409,
      message: "对话存在进行中的问答",
    });
    const rendered = await renderController();
    await waitFor(() =>
      expect(rendered.result.current.thread.runsById.get(9)?.status).toBe(
        "completed",
      ),
    );
    await act(async () => {
      const submitted = await rendered.result.current.submitDraftAction(9);
      expect(submitted).toBe(false);
    });
    expect(rendered.result.current.draftActionError).toContain("进行中的回答");
    expect(rendered.result.current.draftActionPending).toBe(false);
    expect(rendered.result.current.draftsById.size).toBe(0);
  });

  test("整理动作网络结果未知：重试复用同一幂等键", async () => {
    api.listConversations.mockResolvedValue([conversation(1)]);
    api.getConversation.mockResolvedValue(conversation(1));
    api.listMessages.mockResolvedValue({
      items: [message(1, "user", 9), message(2, "assistant", 9)],
      nextCursor: null,
      runs: [answeredRun(9, "completed")],
      candidateDrafts: [],
    });
    (api.submitDraftAction as jest.Mock)
      .mockRejectedValueOnce(new TypeError("Network request failed"))
      .mockResolvedValueOnce({
        userMessage: message(3, "user", 10),
        run: { ...run(10, "waiting"), runKind: "draft_candidate" },
        draft: draft(1),
      });
    const rendered = await renderController();
    await waitFor(() =>
      expect(rendered.result.current.thread.runsById.get(9)?.status).toBe(
        "completed",
      ),
    );
    await act(async () => {
      const first = await rendered.result.current.submitDraftAction(9);
      expect(first).toBe(false);
    });
    expect(rendered.result.current.draftActionError).toContain(
      "Network request failed",
    );
    await act(async () => {
      const retried = await rendered.result.current.retryDraftAction();
      expect(retried).toBe(true);
    });
    expect(api.submitDraftAction).toHaveBeenCalledTimes(2);
    const calls = (api.submitDraftAction as jest.Mock).mock.calls;
    expect(calls[0][2].clientMessageId).toBe(calls[1][2].clientMessageId);
  });

  test("确认草稿未知结果重试复用同一幂等键并更新草稿状态", async () => {
    api.listConversations.mockResolvedValue([conversation(1)]);
    api.getConversation.mockResolvedValue(conversation(1));
    api.listMessages.mockResolvedValue({
      items: [
        message(1, "user", 10, "整理成知识"),
        message(2, "assistant", 10),
      ],
      nextCursor: null,
      runs: [{ ...run(10, "completed"), runKind: "draft_candidate" }],
      candidateDrafts: [
        draft(1, {
          status: "draft",
          title: "闭水试验要点",
          content: "闭水试验通常持续 24 小时。",
          evidenceHandles: ["ev_1"],
        }),
      ],
    });
    (api.confirmDraft as jest.Mock)
      .mockRejectedValueOnce(new TypeError("Network request failed"))
      .mockResolvedValueOnce({
        draft: draft(1, {
          status: "confirmed",
          title: "闭水试验要点",
          content: "闭水试验通常持续 24 小时。",
          confirmedCandidateId: 99,
        }),
        candidate: {
          id: 99,
          title: "闭水试验要点",
          status: "pending",
          sourceId: 12,
          routingStatus: "pending",
          relationStatus: "pending",
          createdAt: "2026-08-29T10:00:00Z",
        },
      });
    const rendered = await renderController();
    await waitFor(() =>
      expect(rendered.result.current.draftsById.get(1)?.status).toBe("draft"),
    );
    await act(async () => {
      const first = await rendered.result.current.confirmDraft(1);
      expect(first).toBe(false);
    });
    expect(rendered.result.current.draftConfirmError).toContain(
      "Network request failed",
    );
    await act(async () => {
      const retried = await rendered.result.current.retryConfirmDraft(1);
      expect(retried).toBe(true);
    });
    await waitFor(() =>
      expect(rendered.result.current.draftsById.get(1)?.status).toBe(
        "confirmed",
      ),
    );
    const calls = (api.confirmDraft as jest.Mock).mock.calls;
    expect(calls[0][2].clientOperationId).toBe(calls[1][2].clientOperationId);
  });

  test("编辑草稿更新服务端权威 Draft", async () => {
    api.listConversations.mockResolvedValue([conversation(1)]);
    api.getConversation.mockResolvedValue(conversation(1));
    api.listMessages.mockResolvedValue({
      items: [
        message(1, "user", 10, "整理成知识"),
        message(2, "assistant", 10),
      ],
      nextCursor: null,
      runs: [{ ...run(10, "completed"), runKind: "draft_candidate" }],
      candidateDrafts: [
        draft(1, {
          status: "draft",
          title: "原标题",
          content: "原内容",
        }),
      ],
    });
    api.editDraft.mockResolvedValue(
      draft(1, { status: "draft", title: "新标题", content: "新内容" }),
    );
    const rendered = await renderController();
    await waitFor(() =>
      expect(rendered.result.current.draftsById.get(1)?.title).toBe("原标题"),
    );
    await act(async () => {
      const edited = await rendered.result.current.editDraft(1, {
        title: "新标题",
        content: "新内容",
      });
      expect(edited).toBe(true);
    });
    expect(rendered.result.current.draftsById.get(1)?.title).toBe("新标题");
    expect(api.editDraft).toHaveBeenCalledWith("token", 1, {
      title: "新标题",
      content: "新内容",
    });
  });

  test("取消草稿失败展示独立错误，不写入编辑错误", async () => {
    api.listConversations.mockResolvedValue([conversation(1)]);
    api.getConversation.mockResolvedValue(conversation(1));
    api.listMessages.mockResolvedValue({
      items: [
        message(1, "user", 10, "整理成知识"),
        message(2, "assistant", 10),
      ],
      nextCursor: null,
      runs: [{ ...run(10, "completed"), runKind: "draft_candidate" }],
      candidateDrafts: [draft(1, { status: "draft" })],
    });
    (api.cancelDraft as jest.Mock).mockRejectedValue(new Error("取消失败"));
    const rendered = await renderController();
    await waitFor(() =>
      expect(rendered.result.current.draftsById.get(1)?.status).toBe("draft"),
    );
    await act(async () => {
      const cancelled = await rendered.result.current.cancelDraft(1);
      expect(cancelled).toBe(false);
    });
    expect(rendered.result.current.draftCancelError).toContain("取消失败");
    expect(rendered.result.current.draftEditError).toBeNull();
    await act(async () => {
      rendered.result.current.clearDraftCancelError();
    });
    expect(rendered.result.current.draftCancelError).toBeNull();
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
