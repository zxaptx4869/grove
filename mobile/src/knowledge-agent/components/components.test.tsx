import { fireEvent, render } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import { AnswerCard } from "@/src/knowledge-agent/components/AnswerCard";
import { CitationSheet } from "@/src/knowledge-agent/components/CitationSheet";
import { Composer } from "@/src/knowledge-agent/components/Composer";
import { ConversationScreen } from "@/src/knowledge-agent/components/ConversationScreen";
import { HistorySheet } from "@/src/knowledge-agent/components/HistorySheet";
import { ProcessCard } from "@/src/knowledge-agent/components/ProcessCard";
import { DEFAULT_MODES } from "@/src/knowledge-agent/state/modes";
import type {
  KnowledgeAnswer,
  KnowledgeConflict,
  KnowledgeConversation,
  KnowledgeRun,
  KnowledgeRunCitation,
} from "@/src/knowledge-agent/types";

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ token: "token", me: null }),
}));

jest.mock("@/src/api", () => ({
  getProjects: jest.fn().mockResolvedValue([]),
}));

jest.mock("@/src/knowledge-agent/api", () => ({
  knowledgeAgentApi: {
    listConversations: jest.fn().mockResolvedValue([]),
    createConversation: jest.fn(),
    getConversation: jest.fn(),
    changeScope: jest.fn(),
    listMessages: jest.fn().mockResolvedValue({
      items: [],
      nextCursor: null,
      runs: [],
    }),
    submitMessage: jest.fn(),
    getRun: jest.fn(),
    cancelRun: jest.fn(),
  },
}));

jest.mock("react-native-safe-area-context", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  return {
    SafeAreaProvider: ({ children }: { children: React.ReactNode }) =>
      React.createElement(View, null, children),
    SafeAreaView: ({ children, ...rest }: Record<string, unknown>) =>
      React.createElement(View, rest, children),
    useSafeAreaInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }),
  };
});

const queryClients: QueryClient[] = [];

afterEach(() => {
  for (const client of queryClients) {
    client.clear();
  }
  queryClients.length = 0;
});

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  queryClients.push(client);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function citation(id: number, overrides: Partial<KnowledgeRunCitation> = {}): KnowledgeRunCitation {
  return {
    evidenceId: id,
    evidenceHandle: `ev_${id}`,
    entryId: id,
    entryTitle: `Entry ${id}`,
    sourceId: id,
    sourceTitle: `来源 ${id}`,
    attachmentId: null,
    quote: `原文片段 ${id}`,
    scopeType: "workspace",
    projectId: null,
    projectName: null,
    nodePath: "施工 / 防水",
    ...overrides,
  };
}

function conflict(a: number, b: number): KnowledgeConflict {
  return {
    summary: "两种口径不一致",
    evidenceIdA: a,
    entryIdA: a,
    entryTitleA: `Entry A${a}`,
    evidenceIdB: b,
    entryIdB: b,
    entryTitleB: `Entry B${b}`,
    citationA: citation(a, { entryTitle: `Entry A${a}`, projectName: "项目甲" }),
    citationB: citation(b, { entryTitle: `Entry B${b}`, projectName: "项目乙" }),
  };
}

function run(
  id: number,
  status: KnowledgeRun["status"],
  answer: KnowledgeAnswer | null,
  overrides: Partial<KnowledgeRun> = {},
): KnowledgeRun {
  return {
    id,
    conversationId: 1,
    status,
    currentStep: null,
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
    answer,
    createdAt: "2026-08-29T10:00:00Z",
    updatedAt: "2026-08-29T10:00:00Z",
    ...overrides,
  };
}

function conversation(id: number): KnowledgeConversation {
  return {
    id,
    title: `对话 ${id}`,
    scopeType: "project",
    projectId: id,
    projectName: "新房装修",
    activeTopicLabel: "防水",
    activeContextVersionId: null,
    activeEntryCount: 3,
    recentRunId: 9,
    recentRunStatus: "completed",
    recentRunCurrentStep: null,
    recentRunUpdatedAt: "2026-08-29T10:00:00Z",
    lastActivityAt: "2026-08-29T10:00:00Z",
    createdAt: "2026-08-29T09:00:00Z",
  };
}

test("composer 空文本禁用发送，模式覆盖显示可移除 chip", async () => {
  const onSend = jest.fn();
  const onRemove = jest.fn();
  const view = await render(
    <Composer
      value=""
      onChangeText={jest.fn()}
      onSend={onSend}
      modes={DEFAULT_MODES}
      onOpenModes={jest.fn()}
      onRemoveContextOverride={onRemove}
      onRemoveAnswerOverride={onRemove}
      submitting={false}
      disabled={false}
    />,
  );
  await fireEvent.press(view.getByLabelText("发送"));
  expect(onSend).not.toHaveBeenCalled();

  await view.rerender(
    <Composer
      value="问题"
      onChangeText={jest.fn()}
      onSend={onSend}
      modes={{ contextMode: "continue", answerMode: "investigate" }}
      onOpenModes={jest.fn()}
      onRemoveContextOverride={onRemove}
      onRemoveAnswerOverride={onRemove}
      submitting={false}
      disabled={false}
    />,
  );
  expect(view.getByText("继续当前主题")).toBeOnTheScreen();
  expect(view.getByText("深度查找")).toBeOnTheScreen();
  await fireEvent.press(view.getByLabelText("移除继续当前主题设置"));
  expect(onRemove).toHaveBeenCalled();
  await fireEvent.press(view.getByLabelText("发送"));
  expect(onSend).toHaveBeenCalledWith();
});

test("五种回答状态区分展示，知识不足不显示成功文案", async () => {
  const statuses: KnowledgeAnswer["status"][] = [
    "completed",
    "partial",
    "insufficient",
    "failed",
    "clarification",
  ];
  for (const status of statuses) {
    const citationsFor = status === "insufficient" ? [] : [citation(1)];
    const view = await render(
      <AnswerCard
        run={run(1, "completed", {
          answer: "正文内容",
          status,
          insufficientNote: "没有足够证据",
          citations: citationsFor,
          conflicts: [],
        })}
        scopeLabel="全部知识"
        onCitationPress={jest.fn()}
        onRetry={jest.fn()}
      />,
      { wrapper },
    );
    if (status === "insufficient") {
      expect(view.getAllByText("知识不足").length).toBeGreaterThan(0);
      expect(view.queryByText("综合回答")).toBeNull();
    } else if (status === "clarification") {
      expect(view.getAllByText("需要澄清").length).toBeGreaterThan(0);
    } else if (status === "failed") {
      expect(view.getAllByText("回答失败").length).toBeGreaterThan(0);
    } else {
      expect(view.getByText("综合回答")).toBeOnTheScreen();
    }
    await view.unmount();
  }
});

test("insufficient 但有引用与实质内容时按部分结果展示并保留引用", async () => {
  const view = await render(
    <AnswerCard
      run={run(1, "completed", {
        answer: "厨房推荐使用 4000K 色温。",
        status: "insufficient",
        insufficientNote: "调查因证据预算停止。",
        citations: [citation(1)],
        conflicts: [],
      })}
      scopeLabel="全部知识"
      onCitationPress={jest.fn()}
      onRetry={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getAllByText("部分结果").length).toBeGreaterThan(0);
  expect(view.getByText("综合回答")).toBeOnTheScreen();
  expect(view.getByLabelText("查看引用：Entry 1")).toBeOnTheScreen();
});

test("过程卡轮询失败显示就地重试", async () => {
  const onRetry = jest.fn();
  const view = await render(
    <ProcessCard
      run={run(9, "processing", null)}
      scopeLabel="全部知识"
      cancelling={false}
      pollingError="连接超时，请检查网络后重试"
      onCancel={jest.fn()}
      onRetryPolling={onRetry}
    />,
  );
  expect(view.getByText(/状态更新失败/)).toBeOnTheScreen();
  await fireEvent.press(view.getByLabelText("重试获取回答状态"));
  expect(onRetry).toHaveBeenCalled();
});

test("冲突卡并列展示双边完整 citation 与项目归属", async () => {
  const onCitationPress = jest.fn();
  const view = await render(
    <AnswerCard
      run={run(2, "completed", {
        answer: "两种口径并存",
        status: "completed",
        insufficientNote: null,
        citations: [citation(1), citation(2)],
        conflicts: [conflict(1, 2)],
      })}
      scopeLabel="全部知识"
      onCitationPress={onCitationPress}
      onRetry={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText("冲突观点")).toBeOnTheScreen();
  expect(view.getByText(/Entry A1/)).toBeOnTheScreen();
  expect(view.getByText(/Entry B2/)).toBeOnTheScreen();
  await fireEvent.press(view.getAllByText(/查看原文/)[0]);
  expect(onCitationPress).toHaveBeenCalled();
});

test("引用 Sheet 分区展示 Entry、项目/目录、Source 原文快照", async () => {
  const onClose = jest.fn();
  const view = await render(
    <CitationSheet
      citation={citation(3, {
        entryTitle: "闭水试验时长",
        projectName: "新房装修",
        nodePath: "施工 / 防水",
        sourceTitle: "验收记录.md",
        quote: "闭水期间应持续观察水位变化",
      })}
      onClose={onClose}
    />,
  );
  expect(view.getByText("闭水试验时长")).toBeOnTheScreen();
  expect(view.getByText("新房装修 / 施工 / 防水")).toBeOnTheScreen();
  expect(view.getByText(/本次回答核验的 SOURCE 原文/)).toBeOnTheScreen();
  expect(view.getByText(/“闭水期间应持续观察水位变化”/)).toBeOnTheScreen();
  expect(view.getByText(/Source：验收记录\.md/)).toBeOnTheScreen();
  expect(view.getByText("查看当前知识（暂不可用）")).toBeOnTheScreen();
  await fireEvent.press(view.getAllByLabelText("关闭")[0]);
  expect(onClose).toHaveBeenCalled();
});

test("历史 Sheet 展示范围、最近 Run 状态并支持选择/新建", async () => {
  const onSelect = jest.fn();
  const onNew = jest.fn();
  const view = await render(
    <HistorySheet
      visible
      conversations={[conversation(1), conversation(2)]}
      activeConversationId={1}
      loading={false}
      error={null}
      onSelect={onSelect}
      onNew={onNew}
      onClose={jest.fn()}
    />,
  );
  expect(view.getAllByText("新房装修").length).toBeGreaterThan(0);
  expect(view.getAllByText(/项目范围 · 已回答/).length).toBeGreaterThan(0);
  await fireEvent.press(view.getByLabelText("切换到对话：对话 2"));
  expect(onSelect).toHaveBeenCalledWith(2);
  await fireEvent.press(view.getByLabelText("新建对话"));
  expect(onNew).toHaveBeenCalled();
});

test("无历史对话时进入本地 draft 空态，可输入", async () => {
  const view = await render(<ConversationScreen />, { wrapper });
  expect(await view.findByText("和你的知识一起想")).toBeOnTheScreen();
  const input = view.getByLabelText("对话输入");
  await fireEvent.changeText(input, "  闭水试验多久？  ");
  expect(view.getByLabelText("发送").props.accessibilityState.disabled).toBe(false);
});

test("提交网络失败保留 pending 并显示就地重试", async () => {
  const api = knowledgeAgentApi as jest.Mocked<typeof knowledgeAgentApi>;
  api.createConversation.mockResolvedValue({
    id: 10,
    title: "新对话",
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
  });
  api.getConversation.mockResolvedValue({
    id: 10,
    title: "新对话",
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
  });
  api.submitMessage.mockRejectedValueOnce(
    new TypeError("Network request failed"),
  );

  const view = await render(<ConversationScreen />, { wrapper });
  const input = await view.findByLabelText("对话输入");
  await fireEvent.changeText(input, "闭水试验多久？");
  await fireEvent.press(view.getByLabelText("发送"));

  expect(await view.findByText("发送未完成")).toBeOnTheScreen();
  expect(view.getByLabelText("重试发送")).toBeOnTheScreen();
  expect(view.getByText("闭水试验多久？")).toBeOnTheScreen();
});
