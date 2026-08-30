import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StyleSheet } from "react-native";

import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import { AnswerCard } from "@/src/knowledge-agent/components/AnswerCard";
import { CitationSheet } from "@/src/knowledge-agent/components/CitationSheet";
import { Composer } from "@/src/knowledge-agent/components/Composer";
import { ConversationScreen } from "@/src/knowledge-agent/components/ConversationScreen";
import {
  DraftCard,
  DraftFailedCard,
  DraftProcessCard,
  DraftReceiptCard,
} from "@/src/knowledge-agent/components/DraftCard";
import { DraftConfirmSheet } from "@/src/knowledge-agent/components/DraftConfirmSheet";
import { DraftEditSheet } from "@/src/knowledge-agent/components/DraftEditSheet";
import { HistorySheet } from "@/src/knowledge-agent/components/HistorySheet";
import { ProcessCard } from "@/src/knowledge-agent/components/ProcessCard";
import { TargetProjectSheet } from "@/src/knowledge-agent/components/TargetProjectSheet";
import { DEFAULT_MODES } from "@/src/knowledge-agent/state/modes";
import type {
  KnowledgeAnswer,
  KnowledgeCandidateDraft,
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
      candidateDrafts: [],
    }),
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

afterEach(async () => {
  // 先卸载订阅 QueryClient 的组件，再取消/清空查询；否则 cancelQueries 的
  // 通知可能在组件仍挂载时跨出 act 边界，形成偶发的 React 测试警告。
  cleanup();
  await act(async () => {
    await Promise.all(queryClients.map((client) => client.cancelQueries()));
    // Query 通知经由零延迟任务批量投递；在 act 内排空该批次。
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
  for (const client of queryClients) {
    client.clear();
  }
  queryClients.length = 0;
});

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
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
    runKind: "answer",
    sourceRunId: null,
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

function draftFixture(
  overrides: Partial<KnowledgeCandidateDraft> = {},
): KnowledgeCandidateDraft {
  return {
    id: 1,
    conversationId: 1,
    operationRunId: 10,
    sourceRunId: 5,
    targetProjectId: 1,
    targetProjectName: "新房装修",
    status: "draft",
    title: "卫生间防水施工与验收要点",
    content:
      "基层处理、重点部位加强、防水层施工和闭水试验应形成连续的检查记录。",
    mainType: "knowledge",
    infoNature: "fact",
    evidenceHandles: ["ev_1"],
    evidenceSummaries: [
      {
        handle: "ev_1",
        entryId: 1,
        entryTitle: "闭水试验",
        sourceId: 1,
        sourceTitle: "验收手册",
        quote: "闭水试验通常持续 24 小时",
      },
    ],
    generationDegraded: false,
    generationError: null,
    confirmedCandidateId: null,
    error: null,
    createdAt: "2026-08-29T10:00:00Z",
    updatedAt: "2026-08-29T10:00:00Z",
    ...overrides,
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
        onOrganize={jest.fn()}
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

test("insufficient 带引用时仍遵循后端知识不足状态", async () => {
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
      onOrganize={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getAllByText("知识不足").length).toBeGreaterThan(0);
  expect(view.queryByText("综合回答")).toBeNull();
  expect(view.getByLabelText("查看引用：Entry 1")).toBeOnTheScreen();
});

test("结构化要点渲染分组标题、连续编号与底部来源条", async () => {
  const onCitationPress = jest.fn();
  const view = await render(
    <AnswerCard
      run={run(1, "completed", {
        answer:
          "结论摘要。\n\n**客厅/卧室区域**\n- 飘窗处预留插座。\n\n**厨房区域**\n- 台面多留插座。",
        status: "completed",
        insufficientNote: null,
        points: [
          {
            section: "客厅/卧室区域",
            text: "飘窗处预留插座。",
            citations: [citation(1)],
          },
          {
            section: "客厅/卧室区域",
            text: "窗帘盒边预留电源。",
            citations: [citation(2)],
          },
          {
            section: "厨房区域",
            text: "台面多留插座。",
            citations: [citation(3)],
          },
        ],
        citations: [citation(1), citation(2), citation(3)],
        conflicts: [],
      })}
      scopeLabel="全部知识"
      onCitationPress={onCitationPress}
      onRetry={jest.fn()}
      onOrganize={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText("▍ 客厅/卧室区域")).toBeOnTheScreen();
  expect(view.getByText("▍ 厨房区域")).toBeOnTheScreen();
  expect(view.getByText(/飘窗处预留插座。/)).toBeOnTheScreen();
  expect(view.getByText(/窗帘盒边预留电源。/)).toBeOnTheScreen();
  expect(view.getByText(/台面多留插座。/)).toBeOnTheScreen();
  // 每条要点左侧连续编号圆点，不裸露 Markdown 标记
  expect(view.getByText("1")).toBeOnTheScreen();
  expect(view.getByText("2")).toBeOnTheScreen();
  expect(view.getByText("3")).toBeOnTheScreen();
  expect(view.queryByText(/\*\*/)).toBeNull();
  // 底部统一来源条，点击打开对应引用
  expect(view.getByLabelText("查看引用：Entry 1")).toBeOnTheScreen();
  expect(view.getByLabelText("查看引用：Entry 3")).toBeOnTheScreen();
  await fireEvent.press(view.getByLabelText("查看引用：Entry 2"));
  expect(onCitationPress).toHaveBeenCalledWith(citation(2));
  // 不再渲染行内上标
  expect(view.queryByText("①")).toBeNull();
  await view.unmount();
});

test("无结构化要点时回退纯文本与底部来源条", async () => {
  const view = await render(
    <AnswerCard
      run={run(1, "completed", {
        answer: "**客厅/卧室区域**\n- 飘窗处预留插座。",
        status: "completed",
        insufficientNote: null,
        citations: [citation(1)],
        conflicts: [],
      })}
      scopeLabel="全部知识"
      onCitationPress={jest.fn()}
      onRetry={jest.fn()}
      onOrganize={jest.fn()}
    />,
    { wrapper },
  );
  // 清洗后展示，不裸露 ** 标记
  expect(view.getByText(/客厅\/卧室区域/)).toBeOnTheScreen();
  expect(view.queryByText(/\*\*/)).toBeNull();
  // 底部引用条仍可访问
  expect(view.getByLabelText("查看引用：Entry 1")).toBeOnTheScreen();
  await view.unmount();
});

test("partial 提供修改问题再问，失败/降级才提供一键重新提问", async () => {
  const partialRefine = jest.fn();
  const partial = await render(
    <AnswerCard
      run={run(1, "partial", {
        answer: "闭水试验已有时长证据。",
        status: "partial",
        insufficientNote: null,
        citations: [citation(1)],
        conflicts: [],
      })}
      scopeLabel="全部知识"
      onCitationPress={jest.fn()}
      onRetry={partialRefine}
      onOrganize={jest.fn()}
      onRefineQuestion={partialRefine}
    />,
    { wrapper },
  );
  expect(partial.queryByLabelText("重新提问")).toBeNull();
  await fireEvent.press(partial.getByLabelText("修改问题再问"));
  expect(partialRefine).toHaveBeenCalledTimes(1);
  await partial.unmount();

  const fallbackRetry = jest.fn();
  const fallback = await render(
    <AnswerCard
      run={run(
        2,
        "completed",
        {
          answer: "闭水试验通常持续 24 小时。",
          status: "completed",
          insufficientNote: null,
          citations: [citation(2)],
          conflicts: [],
        },
        {
          fallbackSummary: {
            hasFallback: true,
            stages: [
              {
                isFallback: true,
                purpose: "embedding",
                provider: "test",
                model: null,
                error: null,
              },
            ],
          },
        },
      )}
      scopeLabel="全部知识"
      onCitationPress={jest.fn()}
      onRetry={fallbackRetry}
      onOrganize={jest.fn()}
    />,
    { wrapper },
  );
  await fireEvent.press(fallback.getByLabelText("重新提问"));
  expect(fallbackRetry).toHaveBeenCalledTimes(1);
});

test("过程卡轮询失败显示就地重试", async () => {
  const onRetry = jest.fn();
  const view = await render(
    <ProcessCard
      run={run(9, "processing", null)}
      scopeLabel="全部知识"
      cancelling={false}
      pollingError="连接超时，请检查网络后重试"
      cancelError={null}
      onCancel={jest.fn()}
      onRetryPolling={onRetry}
    />,
  );
  expect(view.getByText(/状态更新失败/)).toBeOnTheScreen();
  expect(view.getByText("状态异常")).toBeOnTheScreen();
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
      onOrganize={jest.fn()}
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
  const thread = view.getByLabelText("知识 Agent 对话");
  expect(StyleSheet.flatten(thread.props.contentContainerStyle).paddingBottom).toBe(18);
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
  // 失败时输入框文本保留，便于就地修改重试
  expect(input.props.value).toBe("闭水试验多久？");
});

test("活动 Run 409 时显示冲突说明且不保留发送中气泡与重试", async () => {
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
  api.submitMessage.mockRejectedValue({
    status: 409,
    message: "存在进行中的问答",
  });

  const view = await render(<ConversationScreen />, { wrapper });
  const input = await view.findByLabelText("对话输入");
  await fireEvent.changeText(input, "第二个问题");
  await fireEvent.press(view.getByLabelText("发送"));

  expect(await view.findByText("发送未完成")).toBeOnTheScreen();
  expect(view.getByText(/已有进行中的回答/)).toBeOnTheScreen();
  expect(view.queryByLabelText("重试发送")).toBeNull();
  expect(view.queryByText("发送中…")).toBeNull();
  await waitFor(() => {
    expect(api.getConversation).toHaveBeenCalledWith("token", 10);
    expect(api.listMessages).toHaveBeenCalledWith("token", 10, null);
  });
});

test("草稿卡使用 AI 建议语义并展示目标项目与来源摘要", async () => {
  const onEdit = jest.fn();
  const onConfirm = jest.fn();
  const onCancel = jest.fn();
  const view = await render(
    <DraftCard
      draft={draftFixture()}
      confirming={false}
      onEdit={onEdit}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />,
    { wrapper },
  );
  expect(view.getByText("AI 草稿 · 未创建候选")).toBeOnTheScreen();
  expect(view.getByText("卫生间防水施工与验收要点")).toBeOnTheScreen();
  expect(view.getByText(/目标项目：新房装修/)).toBeOnTheScreen();
  expect(view.getByText(/1 条核验证据/)).toBeOnTheScreen();
  expect(view.getByText("类型建议：知识")).toBeOnTheScreen();
  await fireEvent.press(view.getByText("编辑并检查"));
  expect(onEdit).toHaveBeenCalled();
  await fireEvent.press(view.getByText("创建待确认知识"));
  expect(onConfirm).toHaveBeenCalled();
  await fireEvent.press(view.getByText("取消"));
  expect(onCancel).toHaveBeenCalled();
  expect(view.queryByText("正式知识已保存")).toBeNull();
  expect(view.queryByText("已归档")).toBeNull();
});

test("降级草稿显示明确降级说明", async () => {
  const view = await render(
    <DraftCard
      draft={draftFixture({ generationDegraded: true })}
      confirming={false}
      onEdit={jest.fn()}
      onConfirm={jest.fn()}
      onCancel={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText(/草稿生成已降级/)).toBeOnTheScreen();
});

test("确认中草稿卡禁用取消，避免取消与确认竞态", async () => {
  const onCancel = jest.fn();
  const view = await render(
    <DraftCard
      draft={draftFixture()}
      confirming
      onEdit={jest.fn()}
      onConfirm={jest.fn()}
      onCancel={onCancel}
    />,
    { wrapper },
  );
  await fireEvent.press(view.getByText("取消"));
  expect(onCancel).not.toHaveBeenCalled();
});

test("生成过程卡只展示可验证阶段并可取消", async () => {
  const onCancel = jest.fn();
  const view = await render(
    <DraftProcessCard
      run={run(10, "processing", null)}
      cancelling={false}
      onCancel={onCancel}
    />,
    { wrapper },
  );
  expect(view.getByText("正在生成候选草稿")).toBeOnTheScreen();
  await fireEvent.press(view.getByText("取消"));
  expect(onCancel).toHaveBeenCalled();
  expect(view.queryByText("正在处理")).toBeNull();
});

test("确认回执明确尚未写入正式知识", async () => {
  const view = await render(
    <DraftReceiptCard
      draft={draftFixture({
        status: "confirmed",
        confirmedCandidateId: 99,
      })}
    />,
    { wrapper },
  );
  expect(view.getByText(/已创建待确认知识/)).toBeOnTheScreen();
  expect(view.getAllByText(/尚未写入正式知识/).length).toBeGreaterThan(0);
  expect(view.getByText(/待确认（#99）/)).toBeOnTheScreen();
  expect(view.queryByText("正式知识")).toBeNull();
});

test("失败草稿保留错误与重试入口", async () => {
  const onRetry = jest.fn();
  const view = await render(
    <DraftFailedCard
      draft={draftFixture({ status: "failed", error: "证据当前无法重新核验" })}
      onRetry={onRetry}
    />,
    { wrapper },
  );
  expect(view.getByText(/证据当前无法重新核验/)).toBeOnTheScreen();
  await fireEvent.press(view.getByText("重新整理"));
  expect(onRetry).toHaveBeenCalled();
  expect(view.queryByText("取消")).toBeNull();
});

test("取消草稿卡不再提供重新整理按钮", async () => {
  const view = await render(
    <DraftFailedCard
      draft={draftFixture({ status: "cancelled" })}
      onRetry={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText(/这次整理已取消/)).toBeOnTheScreen();
  expect(view.queryByText("重新整理")).toBeNull();
});

test("目标项目 Sheet 只列出项目，不展示目录节点", async () => {
  const onSelect = jest.fn();
  const view = await render(
    <TargetProjectSheet
      visible
      options={[
        { id: 1, name: "新房装修" },
        { id: 2, name: "出租房翻新" },
      ]}
      sourceRunId={9}
      submitting={false}
      error={null}
      onSelect={onSelect}
      onClose={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText("新房装修")).toBeOnTheScreen();
  expect(view.getByText("出租房翻新")).toBeOnTheScreen();
  expect(view.getByText(/草稿只采用所选项目的证据/)).toBeOnTheScreen();
  expect(view.queryByText("目录")).toBeNull();
  await fireEvent.press(view.getByLabelText("整理到项目：新房装修"));
  expect(onSelect).toHaveBeenCalledWith(9, 1);
});

test("确认 Sheet 说明不会直接写入正式知识，创建中禁用主按钮", async () => {
  const onConfirm = jest.fn();
  const view = await render(
    <DraftConfirmSheet
      visible
      draft={draftFixture()}
      confirming
      error={null}
      onConfirm={onConfirm}
      onClose={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText("创建中…")).toBeOnTheScreen();
  expect(view.getByText(/不会直接写入正式知识/)).toBeOnTheScreen();
  await fireEvent.press(view.getByText("创建中…"));
  expect(onConfirm).not.toHaveBeenCalled();
});

test("编辑 Sheet 可编辑标题、正文与类型并保存", async () => {
  const onSave = jest.fn();
  const view = await render(
    <DraftEditSheet
      visible
      draft={draftFixture()}
      saving={false}
      error={null}
      onSave={onSave}
      onClose={jest.fn()}
    />,
    { wrapper },
  );
  const titleInput = view.getByLabelText("草稿标题");
  const contentInput = view.getByLabelText("草稿核心内容");
  await fireEvent.changeText(titleInput, "新标题");
  await fireEvent.changeText(contentInput, "新内容");
  await fireEvent.press(view.getByLabelText("类型：方法"));
  await fireEvent.press(view.getByText("保存编辑"));
  expect(onSave).toHaveBeenCalledWith("新标题", "新内容", "method");
});
