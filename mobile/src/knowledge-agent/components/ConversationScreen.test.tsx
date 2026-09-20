import React from "react";
import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ScrollView } from "react-native";

import { ConversationScreen } from "@/src/knowledge-agent/components/ConversationScreen";
import type { ConversationController } from "@/src/knowledge-agent/hooks/useConversationController";
import type { KnowledgeMessage } from "@/src/knowledge-agent/types";

const mockUseConversationController = jest.fn();
const mockGetProjects = jest.fn(async () => []);

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ token: "token", me: null }),
}));

jest.mock("@/src/api", () => ({
  getProjects: () => mockGetProjects(),
}));

jest.mock("@/src/knowledge-agent/hooks/useConversationController", () => ({
  useConversationController: () => mockUseConversationController(),
}));

jest.mock("@/src/knowledge-agent/hooks/useKeyboardHeight", () => ({
  useKeyboardHeight: () => 0,
}));

jest.mock("@/src/knowledge-agent/hooks/useReducedMotion", () => ({
  useReducedMotion: () => false,
}));

jest.mock("@/src/knowledge-agent/components/HistorySheet", () => {
  const ReactModule = jest.requireActual<typeof import("react")>("react");
  const { Pressable: NativePressable, Text: NativeText, View: NativeView } =
    jest.requireActual<typeof import("react-native")>("react-native");
  return {
    HistorySheet: ({
      visible,
      onNew,
      onSelect,
    }: {
      visible: boolean;
      onNew: () => void;
      onSelect: (conversationId: number) => void;
    }) =>
      visible
        ? ReactModule.createElement(
            NativeView,
            null,
            ReactModule.createElement(NativeText, null, "对话历史"),
            ReactModule.createElement(
              NativePressable,
              { accessibilityLabel: "切换到对话：对话一", onPress: () => onSelect(1) },
            ),
            ReactModule.createElement(NativePressable, {
              accessibilityLabel: "新建对话",
              onPress: onNew,
            }),
          )
        : null,
  };
});

jest.mock("@/src/knowledge-agent/components/ScopeSheet", () => {
  const ReactModule = jest.requireActual<typeof import("react")>("react");
  const { Pressable: NativePressable, Text: NativeText } =
    jest.requireActual<typeof import("react-native")>("react-native");
  return {
    ScopeSheet: ({
      visible,
      onChange,
    }: {
      visible: boolean;
      onChange: (scope: { scopeType: "workspace"; projectId: null }) => void;
    }) =>
      visible
        ? ReactModule.createElement(
            NativePressable,
            {
              accessibilityLabel: "全部知识（当前 Workspace 的所有正式知识）",
              onPress: () => onChange({ scopeType: "workspace", projectId: null }),
            },
            ReactModule.createElement(NativeText, null, "当前知识范围"),
          )
        : null,
  };
});

jest.mock("@/src/knowledge-agent/components/ModeSheet", () => ({
  ModeSheet: () => null,
}));

jest.mock("@/src/knowledge-agent/components/EntryDetailSheet", () => ({
  EntryDetailSheet: () => null,
}));

jest.mock("react-native-safe-area-context", () => {
  const ReactModule = jest.requireActual<typeof import("react")>("react");
  const { View: NativeView } =
    jest.requireActual<typeof import("react-native")>("react-native");
  return {
    SafeAreaView: ({ children, ...props }: React.PropsWithChildren<object>) =>
      ReactModule.createElement(NativeView, props, children),
    useSafeAreaInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }),
  };
});

const clients: QueryClient[] = [];

function userMessage(id: number, conversationId = 1): KnowledgeMessage {
  return {
    id,
    conversationId,
    role: "user",
    messageType: "user",
    content: `消息 ${id}`,
    clientMessageId: null,
    runId: null,
    requestContextMode: "auto",
    contextDecision: null,
    standaloneQuery: null,
    topicLabel: null,
    scopeType: "workspace",
    projectId: null,
    projectName: null,
    createdAt: "2026-09-19T10:00:00Z",
  };
}

function controller(
  overrides: Partial<ConversationController> = {},
): ConversationController {
  const activeConversation = {
    id: 1,
    title: "对话一",
    scopeType: "workspace" as const,
    projectId: null,
    projectName: null,
    activeTopicLabel: null,
    activeContextVersionId: null,
    activeEntryCount: 0,
    recentRunId: null,
    recentRunStatus: null,
    recentRunCurrentStep: null,
    recentRunUpdatedAt: null,
    lastActivityAt: "2026-09-19T10:00:00Z",
    createdAt: "2026-09-19T10:00:00Z",
  };
  return {
    initialLoading: false,
    conversationsLoading: false,
    conversations: [activeConversation],
    conversationsError: null,
    activeConversation,
    activeConversationLoading: false,
    isDraft: false,
    userInitiatedDraft: false,
    currentScope: { scopeType: "workspace", projectId: null },
    scopeLabel: "全部知识",
    scopeBusy: false,
    scopeError: null,
    changeScope: jest.fn(async () => undefined),
    switchToConversation: jest.fn(),
    startNewConversation: jest.fn(),
    retryConversations: jest.fn(),
    thread: {
      items: [],
      runsById: new Map(),
      nextCursor: null,
      hasMore: false,
    },
    messagesLoading: false,
    messagesError: null,
    loadOlderMessages: jest.fn(async () => undefined),
    loadingOlder: false,
    olderError: null,
    pending: null,
    input: "",
    setInput: jest.fn(),
    submitting: false,
    submissionResultUnknown: false,
    conversationCreationUnknown: false,
    submitError: null,
    recoveryError: null,
    persistenceError: null,
    retryRecovery: jest.fn(),
    retryPersistence: jest.fn(),
    exitRecovery: jest.fn(async () => undefined),
    getReadingPosition: jest.fn(() => null),
    setReadingPosition: jest.fn(),
    clearReadingPosition: jest.fn(),
    modes: { contextMode: "auto" },
    setContextMode: jest.fn(),
    setModes: jest.fn(),
    submit: jest.fn(async () => true),
    continueRun: jest.fn(async () => true),
    retrySubmit: jest.fn(async () => true),
    retryRun: jest.fn(async () => true),
    resumableRunId: null,
    activeRun: null,
    runPolling: false,
    runPollingError: null,
    retryRunPolling: jest.fn(),
    cancelling: false,
    cancelError: null,
    requestCancelRun: jest.fn(async () => undefined),
    appActive: true,
    ...overrides,
  };
}

function renderScreen() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <ConversationScreen />
    </QueryClientProvider>,
  );
}

afterEach(async () => {
  await cleanup();
  await act(async () => {
    await Promise.all(clients.map((client) => client.cancelQueries()));
  });
  clients.forEach((client) => client.clear());
  clients.length = 0;
  jest.restoreAllMocks();
  jest.clearAllMocks();
});

test("顶部品牌、范围、历史和历史中的新建对话入口均可达", async () => {
  const state = controller();
  mockUseConversationController.mockReturnValue(state);
  const rendered = await renderScreen();

  expect(rendered.getByLabelText("Grove")).toBeTruthy();
  await fireEvent.press(rendered.getByLabelText("修改当前知识范围，当前为全部知识"));
  await waitFor(() => expect(rendered.getByText("当前知识范围")).toBeTruthy());
  await fireEvent.press(
    rendered.getByLabelText("全部知识（当前 Workspace 的所有正式知识）"),
  );
  expect(state.changeScope).toHaveBeenCalledWith({ scopeType: "workspace", projectId: null });

  await fireEvent.press(rendered.getByLabelText("打开对话历史"));
  await waitFor(() => expect(rendered.getByText("对话历史")).toBeTruthy());
  await fireEvent.press(rendered.getByLabelText("切换到对话：对话一"));
  expect(state.switchToConversation).toHaveBeenCalledWith(1);
  await fireEvent.press(rendered.getByLabelText("打开对话历史"));
  await fireEvent.press(rendered.getByLabelText("新建对话"));
  expect(state.startNewConversation).toHaveBeenCalledTimes(1);
});

test("新对话的上次项目失效时提示并回退全部知识", async () => {
  mockGetProjects.mockResolvedValueOnce([]);
  const state = controller({
    activeConversation: null,
    isDraft: true,
    userInitiatedDraft: true,
    currentScope: { scopeType: "project", projectId: 99, projectName: "已失效项目" },
    scopeLabel: "已失效项目",
  });
  mockUseConversationController.mockReturnValue(state);
  const rendered = await renderScreen();

  await fireEvent.press(
    rendered.getByLabelText("修改当前知识范围，当前为已失效项目"),
  );
  await waitFor(() =>
    expect(state.changeScope).toHaveBeenCalledWith({
      scopeType: "workspace",
      projectId: null,
    }),
  );
  expect(rendered.getByText("上次使用的项目已不可用，已切换为全部知识。")).toBeTruthy();
});

test("上次项目范围复验失败时阻止提交并提供重试", async () => {
  mockGetProjects.mockRejectedValueOnce(new TypeError("Network request failed"));
  const state = controller({
    activeConversation: null,
    isDraft: true,
    userInitiatedDraft: true,
    currentScope: { scopeType: "project", projectId: 99, projectName: "待确认项目" },
    scopeLabel: "待确认项目",
    input: "待发送问题",
  });
  mockUseConversationController.mockReturnValue(state);
  const rendered = await renderScreen();

  await waitFor(() => expect(rendered.getByText("上次的知识范围暂时无法确认")).toBeTruthy());
  expect(rendered.getByLabelText("发送").props.accessibilityState.disabled).toBe(true);
  await fireEvent.press(rendered.getByLabelText("重试确认上次知识范围"));
  await waitFor(() => expect(mockGetProjects).toHaveBeenCalledTimes(2));
});

test("正常发送只显示普通发送态，结果未知才显示恢复入口", async () => {
  const pending = {
    clientMessageId: "stable-id",
    text: "普通问题",
    contextMode: "auto" as const,
    conversationId: 1,
    phase: "submitting" as const,
  };
  mockUseConversationController.mockReturnValue(
    controller({ pending, submitting: true, submissionResultUnknown: false }),
  );
  const rendered = await renderScreen();
  expect(rendered.getByText("正在发送")).toBeTruthy();
  expect(rendered.queryByText("消息提交结果尚未确认")).toBeNull();
  expect(rendered.queryByText("恢复这次提交")).toBeNull();

  mockUseConversationController.mockReturnValue(
    controller({
      pending,
      submitting: false,
      submissionResultUnknown: true,
      submitError: "连接超时",
    }),
  );
  await rendered.rerender(
    <QueryClientProvider client={clients[0]}>
      <ConversationScreen />
    </QueryClientProvider>,
  );
  expect(rendered.getByText("消息提交结果尚未确认")).toBeTruthy();
  expect(rendered.getByText("恢复这次提交")).toBeTruthy();
});

test("每次进入或切换会话只初始定位一次，主动上滑后不被轮询拉回底部", async () => {
  const scrollToEnd = jest
    .spyOn(ScrollView.prototype, "scrollToEnd")
    .mockImplementation(() => undefined);
  let state = controller({
    thread: {
      items: [userMessage(1)],
      runsById: new Map(),
      nextCursor: null,
      hasMore: false,
    },
  });
  mockUseConversationController.mockImplementation(() => state);
  const rendered = await renderScreen();
  const thread = rendered.getByLabelText("知识 Agent 对话");

  await fireEvent(thread, "contentSizeChange", 320, 900);
  expect(scrollToEnd).toHaveBeenCalledWith({ animated: false });
  scrollToEnd.mockClear();

  await fireEvent.press(rendered.getByLabelText("打开对话历史"));
  await fireEvent.press(rendered.getByLabelText("切换到对话：对话一"));
  await fireEvent(thread, "contentSizeChange", 320, 900);
  expect(scrollToEnd).toHaveBeenCalledWith({ animated: false });
  scrollToEnd.mockClear();

  await fireEvent.scroll(thread, {
    nativeEvent: {
      contentOffset: { y: 100 },
      contentSize: { height: 900, width: 320 },
      layoutMeasurement: { height: 400, width: 320 },
    },
  });
  state = { ...state, runPolling: true };
  await rendered.rerender(
    <QueryClientProvider client={clients[0]}>
      <ConversationScreen />
    </QueryClientProvider>,
  );
  await fireEvent(
    rendered.getByLabelText("知识 Agent 对话"),
    "contentSizeChange",
    320,
    920,
  );
  expect(scrollToEnd).not.toHaveBeenCalled();

  state = controller({
    activeConversation: { ...state.activeConversation!, id: 2, title: "对话二" },
    conversations: [{ ...state.activeConversation!, id: 2, title: "对话二" }],
    thread: {
      items: [userMessage(2, 2)],
      runsById: new Map(),
      nextCursor: null,
      hasMore: false,
    },
  });
  await rendered.rerender(
    <QueryClientProvider client={clients[0]}>
      <ConversationScreen />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(rendered.getByText("消息 2")).toBeTruthy());
  await fireEvent(
    rendered.getByLabelText("知识 Agent 对话"),
    "contentSizeChange",
    320,
    700,
  );
  expect(scrollToEnd).toHaveBeenCalledTimes(1);
  expect(scrollToEnd).toHaveBeenCalledWith({ animated: false });
});

test("发送新问题会主动跟随到本次发送反馈", async () => {
  const scrollToEnd = jest
    .spyOn(ScrollView.prototype, "scrollToEnd")
    .mockImplementation(() => undefined);
  const state = controller({ input: "新的问题" });
  mockUseConversationController.mockReturnValue(state);
  const rendered = await renderScreen();

  await fireEvent.changeText(rendered.getByLabelText("对话输入"), "新的问题");
  await fireEvent.press(rendered.getByLabelText("发送"));
  expect(state.submit).toHaveBeenCalledWith("新的问题");
  expect(scrollToEnd).toHaveBeenCalledWith({ animated: true });
});

test("同一会话页面重挂载恢复内存阅读位置，不强制跳到底部", async () => {
  const positions = new Map<string, number>();
  const state = controller({
    thread: {
      items: [userMessage(1)],
      runsById: new Map(),
      nextCursor: null,
      hasMore: false,
    },
    getReadingPosition: jest.fn((key) => positions.get(key) ?? null),
    setReadingPosition: jest.fn((key, value) => positions.set(key, value)),
  });
  mockUseConversationController.mockReturnValue(state);
  const scrollTo = jest.spyOn(ScrollView.prototype, "scrollTo").mockImplementation(() => undefined);
  const first = await renderScreen();
  await fireEvent(
    first.getByLabelText("知识 Agent 对话"),
    "contentSizeChange",
    320,
    900,
  );
  await fireEvent.scroll(first.getByLabelText("知识 Agent 对话"), {
    nativeEvent: {
      contentOffset: { x: 0, y: 180 },
      contentSize: { width: 320, height: 900 },
      layoutMeasurement: { width: 320, height: 500 },
    },
  });
  expect(state.setReadingPosition).toHaveBeenCalledWith("1", 180);
  await first.unmount();
  scrollTo.mockClear();

  const restored = await renderScreen();
  await fireEvent(
    restored.getByLabelText("知识 Agent 对话"),
    "contentSizeChange",
    320,
    900,
  );
  expect(scrollTo).toHaveBeenCalledWith({ y: 180, animated: false });
});
