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
import { EntryResultsCard } from "@/src/knowledge-agent/components/EntryResultsCard";
import { ProcessCard } from "@/src/knowledge-agent/components/ProcessCard";
import { RevisionConfirmSheet } from "@/src/knowledge-agent/components/RevisionConfirmSheet";
import { RevisionDiffScreen } from "@/src/knowledge-agent/components/RevisionDiffScreen";
import {
  RevisionDraftCard,
  RevisionDraftFailedCard,
  RevisionProcessCard,
  RevisionReceiptCard,
} from "@/src/knowledge-agent/components/RevisionDraftCard";
import { RevisionEditSheet } from "@/src/knowledge-agent/components/RevisionEditSheet";
import { RevisionInstructionSheet } from "@/src/knowledge-agent/components/RevisionInstructionSheet";
import { RevisionUndoSheet } from "@/src/knowledge-agent/components/RevisionUndoSheet";
import { TargetProjectSheet } from "@/src/knowledge-agent/components/TargetProjectSheet";
import type { RevisionTarget } from "@/src/knowledge-agent/adapters/answer";
import { DEFAULT_MODES } from "@/src/knowledge-agent/state/modes";
import type {
  KnowledgeAnswer,
  KnowledgeCandidateDraft,
  KnowledgeConflict,
  KnowledgeConversation,
  KnowledgeEntryResultItem,
  KnowledgeEntryResultSnapshot,
  KnowledgeEntryRevisionDraft,
  KnowledgeMessage,
  KnowledgeRun,
  KnowledgeRunCitation,
} from "@/src/knowledge-agent/types";
import type { EntryResultsState } from "@/src/knowledge-agent/hooks/useConversationController";

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ token: "token", me: null }),
}));

jest.mock("expo-crypto", () => ({
  randomUUID: () => "test-client-id",
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
    submitEntryRevision: jest.fn(),
    getEntryRevisionDraft: jest.fn(),
    editEntryRevisionDraft: jest.fn(),
    cancelEntryRevisionDraft: jest.fn(),
    confirmEntryRevision: jest.fn(),
    undoEntryRevision: jest.fn(),
    getEntryCurrent: jest.fn(),
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
    requestResultMode: null,
    actualResultMode: null,
    currentRound: 0,
    inputContextVersionId: null,
    outputContextVersionId: null,
    contextDegraded: false,
    fallbackSummary: null,
    investigationSummary: null,
    answer,
    entryResult: null,
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

function structuredEntry(entryId: number): KnowledgeEntryResultItem {
  return {
    entryId,
    title: `防水经验 ${entryId}`,
    excerpt: "正式知识摘要",
    projectId: 1,
    projectName: "新房装修",
    nodeId: 2,
    nodePath: "施工 / 防水",
    mainType: "knowledge",
    infoNature: "experience",
    updatedAt: "2026-09-02T00:00:00Z",
    sourceCount: 1,
    fingerprint: `fp-${entryId}`,
    matchHint: null,
    matchedFields: [],
  };
}

function structuredState(items: KnowledgeEntryResultItem[]): EntryResultsState {
  return {
    runId: 30,
    items,
    nextCursor: null,
    hasMore: false,
    loadingMore: false,
    error: null,
    primed: true,
  };
}

function structuredSnapshot(
  overrides: Partial<KnowledgeEntryResultSnapshot> = {},
): KnowledgeEntryResultSnapshot {
  const items = [structuredEntry(1), structuredEntry(2)];
  return {
    schemaVersion: "v2",
    query: "最近的防水经验",
    status: "completed",
    completeness: "limited",
    items,
    returnedCount: items.length,
    candidateLimit: 6,
    warning: null,
    snapshotUpdatedAt: "2026-09-02T00:00:00Z",
    setSummary: {
      schemaVersion: "v1",
      scopeType: "workspace",
      projectId: null,
      projectName: null,
      semanticQuery: null,
      mainTypes: ["knowledge"],
      infoNatures: ["experience"],
      updatedAtFrom: "2026-08-01T00:00:00Z",
      updatedAtTo: "2026-09-01T00:00:00Z",
      completeness: "complete",
    },
    sort: { field: "updated_at", direction: "desc", tieBreaker: "entry_id" },
    count: { value: 23, completeness: "complete", status: "completed" },
    groupCounts: [
      {
        groupBy: "info_nature",
        buckets: [
          { key: "experience", count: 10 },
          { key: "unspecified", count: 5 },
        ],
        completeness: "complete",
        status: "completed",
        truncated: false,
      },
    ],
    outputCompleteness: {
      entries: "limited",
      count: "complete",
      groupCount: { infoNature: "complete" },
    },
    warnings: [],
    ...overrides,
  };
}

test("结构化查询精确计数、分组与排序按服务端结果展示", async () => {
  const entryResult = structuredSnapshot();
  const view = await render(
    <EntryResultsCard
      run={run(30, "completed", null, {
        actualResultMode: "entries",
        entryResult,
      })}
      scopeLabel="全部知识"
      state={structuredState(entryResult.items)}
      onPrime={jest.fn()}
      onLoadMore={jest.fn()}
      onRetry={jest.fn()}
      onOpenItem={jest.fn()}
      onCorrectMode={jest.fn()}
      onRefine={jest.fn()}
    />,
  );
  expect(view.getByText("共 23 条")).toBeOnTheScreen();
  expect(view.getByText("类型：知识")).toBeOnTheScreen();
  expect(view.getByText("性质：经验")).toBeOnTheScreen();
  expect(view.getByText("按信息性质")).toBeOnTheScreen();
  expect(view.getByText("未标注")).toBeOnTheScreen();
  expect(view.getByText("知识列表 · 按更新时间倒序")).toBeOnTheScreen();
  expect(view.queryByText("Citation")).toBeNull();
});

test("结构化查询 limited 计数使用本次匹配边界而非精确全集", async () => {
  const entryResult = structuredSnapshot({
    setSummary: {
      ...structuredSnapshot().setSummary!,
      semanticQuery: "防水",
      completeness: "limited",
    },
    count: { value: 9, completeness: "limited", status: "limited" },
  });
  const view = await render(
    <EntryResultsCard
      run={run(31, "completed", null, {
        actualResultMode: "entries",
        entryResult,
      })}
      scopeLabel="全部知识"
      state={structuredState(entryResult.items)}
      onPrime={jest.fn()}
      onLoadMore={jest.fn()}
      onRetry={jest.fn()}
      onOpenItem={jest.fn()}
      onCorrectMode={jest.fn()}
      onRefine={jest.fn()}
    />,
  );
  expect(view.getByText("本次匹配到 9 条")).toBeOnTheScreen();
  expect(view.getByText(/不代表当前范围内的全部知识/)).toBeOnTheScreen();
  expect(view.queryByText("共 9 条")).toBeNull();
});

test("查询结果空集合保留服务端精确零计数和可操作空态", async () => {
  const entryResult = structuredSnapshot({
    items: [],
    returnedCount: 0,
    completeness: "complete",
    count: { value: 0, completeness: "complete", status: "empty" },
    groupCounts: [],
    outputCompleteness: {
      entries: null,
      count: "complete",
      groupCount: {},
    },
    sort: null,
  });
  const onRefine = jest.fn();
  const view = await render(
    <EntryResultsCard
      run={run(32, "completed", null, {
        actualResultMode: "entries",
        entryResult,
      })}
      scopeLabel="全部知识"
      state={structuredState([])}
      onPrime={jest.fn()}
      onLoadMore={jest.fn()}
      onRetry={jest.fn()}
      onOpenItem={jest.fn()}
      onCorrectMode={jest.fn()}
      onRefine={onRefine}
    />,
  );
  expect(view.getByText("共 0 条")).toBeOnTheScreen();
  expect(view.getByText("没有找到匹配的正式知识")).toBeOnTheScreen();
  await fireEvent.press(view.getByLabelText("修改问题"));
  expect(onRefine).toHaveBeenCalled();
});

test("查询结果长分组有界展开并保留服务端桶截断提示", async () => {
  const entryResult = structuredSnapshot({
    groupCounts: [
      {
        groupBy: "info_nature",
        buckets: [
          { key: "fact", count: 8 },
          { key: "experience", count: 7 },
          { key: "advice", count: 6 },
          { key: "speculation", count: 5 },
          { key: "other", count: 4 },
          { key: "unspecified", count: 3 },
        ],
        completeness: "complete",
        status: "limited",
        truncated: true,
      },
    ],
  });
  const view = await render(
    <EntryResultsCard
      run={run(33, "completed", null, {
        actualResultMode: "entries",
        entryResult,
      })}
      scopeLabel="全部知识"
      state={structuredState(entryResult.items)}
      onPrime={jest.fn()}
      onLoadMore={jest.fn()}
      onRetry={jest.fn()}
      onOpenItem={jest.fn()}
      onCorrectMode={jest.fn()}
      onRefine={jest.fn()}
    />,
  );
  expect(view.queryByText("未标注")).toBeNull();
  expect(view.getByText(/仅显示服务端返回的前几组/)).toBeOnTheScreen();
  await fireEvent.press(view.getByLabelText("展开按信息性质其余 2 组"));
  expect(view.getByText("未标注")).toBeOnTheScreen();
});

test("查询结果聚合成功但列表 partial 时不降低精确计数", async () => {
  const entryResult = structuredSnapshot({
    status: "partial",
    completeness: "unknown",
    items: [structuredEntry(1)],
    returnedCount: 1,
    outputCompleteness: {
      entries: "unknown",
      count: "complete",
      groupCount: { infoNature: "complete" },
    },
    warnings: ["一条历史 Entry 当前不可用"],
  });
  const view = await render(
    <EntryResultsCard
      run={run(34, "partial", null, {
        actualResultMode: "entries",
        entryResult,
      })}
      scopeLabel="全部知识"
      state={structuredState(entryResult.items)}
      onPrime={jest.fn()}
      onLoadMore={jest.fn()}
      onRetry={jest.fn()}
      onOpenItem={jest.fn()}
      onCorrectMode={jest.fn()}
      onRefine={jest.fn()}
    />,
  );
  expect(view.getByText("共 23 条")).toBeOnTheScreen();
  expect(view.getByText(/部分匹配对象当前不可用/)).toBeOnTheScreen();
  expect(view.getByText("一条历史 Entry 当前不可用")).toBeOnTheScreen();
  expect(view.getByText("防水经验 1")).toBeOnTheScreen();
});

test("结构化查询保持知识列表结果形态并满足可访问只读边界", async () => {
  const entryResult = structuredSnapshot({
    groupCounts: [
      {
        groupBy: "info_nature",
        buckets: [
          { key: "fact", count: 8 },
          { key: "experience", count: 7 },
          { key: "advice", count: 6 },
          { key: "speculation", count: 5 },
          { key: "unspecified", count: 4 },
        ],
        completeness: "complete",
        status: "completed",
        truncated: false,
      },
    ],
  });
  const view = await render(
    <EntryResultsCard
      run={run(35, "completed", null, {
        requestResultMode: "auto",
        actualResultMode: "entries",
        entryResult,
      })}
      scopeLabel="全部知识"
      state={{ ...structuredState(entryResult.items), hasMore: true }}
      onPrime={jest.fn()}
      onLoadMore={jest.fn()}
      onRetry={jest.fn()}
      onOpenItem={jest.fn()}
      onCorrectMode={jest.fn()}
      onRefine={jest.fn()}
    />,
  );
  expect(view.getByText("结构化知识查询")).toBeOnTheScreen();
  expect(view.queryByText("综合回答")).toBeNull();
  expect(view.queryByText(/Citation|引用|整理成知识|修订|勾选|全选|批量/)).toBeNull();
  expect(view.getByLabelText(/筛选条件：/)).toBeOnTheScreen();
  expect(view.getByLabelText("第 1 条，正式知识，防水经验 1，新房装修 / 施工 / 防水"))
    .toBeOnTheScreen();
  const expand = view.getByLabelText("展开按信息性质其余 1 组");
  expect(StyleSheet.flatten(expand.props.style).minHeight).toBeGreaterThanOrEqual(44);
  const loadMore = view.getByLabelText("加载更多结果");
  expect(StyleSheet.flatten(loadMore.props.style).minHeight).toBeGreaterThanOrEqual(44);
  const correct = view.getByLabelText("改为综合回答");
  expect(StyleSheet.flatten(correct.props.style).minHeight).toBeGreaterThanOrEqual(44);
});

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
    requestResultMode: null,
    actualResultMode: null,
    currentRound: 0,
    inputContextVersionId: null,
    outputContextVersionId: null,
    createdAt: new Date(id * 1000).toISOString(),
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
    routingStatus: null,
    relationStatus: null,
    error: null,
    createdAt: "2026-08-29T10:00:00Z",
    updatedAt: "2026-08-29T10:00:00Z",
    ...overrides,
  };
}

function revisionDraftFixture(
  overrides: Partial<KnowledgeEntryRevisionDraft> = {},
): KnowledgeEntryRevisionDraft {
  return {
    id: 30,
    conversationId: 1,
    operationRunId: 40,
    sourceRunId: 5,
    targetEntryId: 1,
    targetProjectId: 1,
    targetProjectName: "新房装修",
    instruction: "补充适用条件",
    status: "draft",
    title: "闭水试验完成后再验收防水层（含适用条件）",
    content: "闭水试验应持续观察水位与楼下顶面。",
    mainType: "method",
    infoNature: "advice",
    applicableCondition: "材料说明未覆盖时按现场条件确认",
    note: null,
    changeSummary: "补充适用条件与观察要求",
    reason: "依据防水验收记录原文",
    selectedEvidenceHandles: ["ev_1"],
    evidenceSummaries: [
      {
        handle: "ev_1",
        entryId: 1,
        entryTitle: "闭水试验",
        sourceId: 1,
        sourceTitle: "防水验收记录.md",
        quote: "闭水期间应持续观察水位变化",
      },
    ],
    changedFields: [
      { field: "content", label: "核心内容", before: "旧内容", after: "新内容" },
      { field: "applicable_condition", label: "适用条件", before: null, after: "按现场条件" },
    ],
    generationDegraded: false,
    generationError: null,
    execution: null,
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
      onRemoveResultOverride={onRemove}
      onRemoveBasisOverride={onRemove}
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
      modes={{
        contextMode: "continue",
        answerMode: "investigate",
        resultMode: "entries",
        basisMode: "knowledge_only",
      }}
      onOpenModes={jest.fn()}
      onRemoveContextOverride={onRemove}
      onRemoveAnswerOverride={onRemove}
      onRemoveResultOverride={onRemove}
      onRemoveBasisOverride={onRemove}
      submitting={false}
      disabled={false}
    />,
  );
  expect(view.getByText("继续当前主题")).toBeOnTheScreen();
  expect(view.getByText("深度查找")).toBeOnTheScreen();
  expect(view.getByText("仅使用我的知识库")).toBeOnTheScreen();
  await fireEvent.press(view.getByLabelText("移除继续当前主题设置"));
  expect(onRemove).toHaveBeenCalled();
  await fireEvent.press(view.getByLabelText("移除仅使用我的知识库设置"));
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

test("依据概览区分 AI 即时回答与基于你的知识，无引用完成回答正常", async () => {
  const modelOnly = await render(
    <AnswerCard
      run={run(
        1,
        "completed",
        {
          answer: "这是一段开放通用回答。",
          status: "completed",
          insufficientNote: null,
          citations: [],
          conflicts: [],
        },
        {
          answerBasis: {
            schemaVersion: "v1",
            grove: { used: false, citationCount: 0, entryCount: 0 },
            userStatements: { messageIds: [] },
            modelKnowledge: { used: true },
            externalMaterial: { status: "not_used" },
          },
        },
      )}
      scopeLabel="全部知识"
      onCitationPress={jest.fn()}
      onRetry={jest.fn()}
      onOrganize={jest.fn()}
    />,
    { wrapper },
  );
  expect(modelOnly.getAllByText("AI 即时回答").length).toBeGreaterThan(0);
  expect(modelOnly.getByText("综合回答")).toBeOnTheScreen();
  expect(modelOnly.getByText(/AI 通用知识/)).toBeOnTheScreen();
  expect(modelOnly.getByText(/未使用你的知识库/)).toBeOnTheScreen();
  expect(modelOnly.queryByText("整理成知识")).toBeNull();
  await modelOnly.unmount();

  const groveOnly = await render(
    <AnswerCard
      run={run(
        2,
        "completed",
        {
          answer: "基于正式知识的回答。",
          status: "completed",
          insufficientNote: null,
          citations: [citation(1)],
          conflicts: [],
        },
        {
          answerBasis: {
            schemaVersion: "v1",
            grove: { used: true, citationCount: 1, entryCount: 1 },
            userStatements: { messageIds: [] },
            modelKnowledge: { used: false },
            externalMaterial: { status: "not_used" },
          },
        },
      )}
      scopeLabel="全部知识"
      onCitationPress={jest.fn()}
      onRetry={jest.fn()}
      onOrganize={jest.fn()}
    />,
    { wrapper },
  );
  expect(groveOnly.getAllByText("基于你的知识").length).toBeGreaterThan(0);
  expect(groveOnly.getByText("整理成知识")).toBeOnTheScreen();
  await groveOnly.unmount();
});

test("依据详情展示用户陈述与外部材料边界并可定位消息", async () => {
  const onCitationPress = jest.fn();
  const onLocateMessage = jest.fn();
  const messagesById = new Map<number, KnowledgeMessage>([
    [
      3,
      {
        id: 3,
        conversationId: 1,
        role: "user",
        messageType: "user",
        content: "我的预算上限是 30 万",
        clientMessageId: "c-3",
        runId: 1,
        scopeType: "workspace",
        projectId: null,
        projectName: null,
        requestContextMode: null,
        contextDecision: null,
        standaloneQuery: null,
        topicLabel: null,
        requestAnswerMode: null,
        actualAnswerMode: null,
        requestResultMode: null,
        actualResultMode: null,
        currentRound: 0,
        inputContextVersionId: null,
        outputContextVersionId: null,
        createdAt: "2026-08-29T10:00:00Z",
      },
    ],
  ]);
  const view = await render(
    <AnswerCard
      run={run(
        1,
        "completed",
        {
          answer: "混合建议。",
          status: "completed",
          insufficientNote: null,
          citations: [citation(1)],
          conflicts: [],
        },
        {
          answerBasis: {
            schemaVersion: "v1",
            grove: { used: true, citationCount: 1, entryCount: 1 },
            userStatements: { messageIds: [3] },
            modelKnowledge: { used: true },
            externalMaterial: { status: "required_unavailable" },
          },
        },
      )}
      scopeLabel="全部知识"
      onCitationPress={onCitationPress}
      onRetry={jest.fn()}
      onOrganize={jest.fn()}
      messagesById={messagesById}
      onLocateMessage={onLocateMessage}
    />,
    { wrapper },
  );
  expect(view.getAllByText("混合依据").length).toBeGreaterThan(0);
  await fireEvent.press(view.getByLabelText(/回答依据：/));
  expect(view.getByText("你提供的信息")).toBeOnTheScreen();
  expect(view.getByText("我的预算上限是 30 万")).toBeOnTheScreen();
  expect(view.getByText("外部材料边界")).toBeOnTheScreen();
  expect(view.getByText(/未接入实时外部检索/)).toBeOnTheScreen();
  await fireEvent.press(view.getByLabelText("定位到消息 3"));
  expect(onLocateMessage).toHaveBeenCalledWith(3);
  await view.unmount();
});

test("旧回答缺少 basis 时维持现有展示且历史整理入口可恢复", async () => {
  const view = await render(
    <AnswerCard
      run={run(1, "completed", {
        answer: "历史回答。",
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
  expect(view.getAllByText("基于正式知识").length).toBeGreaterThan(0);
  expect(view.queryByLabelText(/回答依据：/)).toBeNull();
  expect(view.getByText("整理成知识")).toBeOnTheScreen();
  await view.unmount();
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

test("复合回答保持现有要点与依据展示，不暴露内部任务拆解", async () => {
  const view = await render(
    <AnswerCard
      run={run(
        18,
        "partial",
        {
          answer: "甲醛是一种化合物。",
          status: "partial",
          insufficientNote: null,
          points: [
            {
              section: "定义",
              text: "甲醛是一种挥发性有机化合物。",
              citations: [],
              requirementIds: ["r1"],
            },
          ],
          citations: [],
          conflicts: [],
        },
        {
          compositeAnswerPlan: {
            schemaVersion: "v1",
            requirements: [
              {
                id: "r1",
                order: 0,
                summary: "内部义务：解释甲醛是什么",
                kind: "explain",
                basisPolicy: "model_allowed",
              },
            ],
            inputKinds: [],
          },
          compositeAnswerCoverage: {
            schemaVersion: "v1",
            requirements: [
              {
                requirementId: "r1",
                summary: "内部义务：解释甲醛是什么",
                status: "answered",
                basisKinds: ["model_knowledge"],
                note: null,
              },
            ],
          },
        },
      )}
      scopeLabel="全部知识"
      onCitationPress={jest.fn()}
      onRetry={jest.fn()}
      onOrganize={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText(/甲醛是一种挥发性有机化合物/)).toBeOnTheScreen();
  expect(view.getAllByText("部分结果").length).toBeGreaterThan(0);
  expect(view.queryByText("内部义务：解释甲醛是什么")).toBeNull();
  expect(view.queryByText("r1")).toBeNull();
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
  const api = knowledgeAgentApi as jest.Mocked<typeof knowledgeAgentApi>;
  (api.getEntryCurrent as jest.Mock).mockResolvedValue({
    id: 3,
    projectId: 1,
    nodeId: 1,
    nodeName: "施工",
    title: "闭水试验时长",
    content: "闭水试验通常持续 24 小时，验收前不得放水。",
    mainType: "method",
    infoNature: "advice",
    applicableCondition: null,
    note: null,
    createdAt: "2026-08-29T09:00:00Z",
    updatedAt: "2026-08-29T10:00:00Z",
  });
  const view = await render(
    <CitationSheet
      citation={citation(3, {
        entryTitle: "闭水试验时长",
        projectName: "新房装修",
        nodePath: "施工 / 防水",
        sourceTitle: "验收记录.md",
        quote: "闭水期间应持续观察水位变化",
      })}
      revisionTargets={[
        {
          entryId: 3,
          entryTitle: "闭水试验时长",
          projectId: 1,
          projectName: "新房装修",
          nodePath: "施工 / 防水",
        },
      ]}
      sourceRunId={9}
      onRevise={jest.fn()}
      onClose={onClose}
    />,
    { wrapper },
  );
  await waitFor(() =>
    expect(view.getByText(/闭水试验通常持续 24 小时/)).toBeOnTheScreen(),
  );
  expect(view.getByText("闭水试验时长")).toBeOnTheScreen();
  expect(view.getByText("新房装修 / 施工 / 防水")).toBeOnTheScreen();
  expect(view.getByText(/闭水试验通常持续 24 小时/)).toBeOnTheScreen();
  expect(view.getByText(/本次回答核验的原文/)).toBeOnTheScreen();
  expect(view.getByText(/“闭水期间应持续观察水位变化”/)).toBeOnTheScreen();
  expect(view.getByText(/来源：验收记录\.md/)).toBeOnTheScreen();
  expect(view.getByText("开始修订")).toBeOnTheScreen();
  // 精简后的快照说明与内部校验话术
  expect(view.getByText(/回答生成时的快照/)).toBeOnTheScreen();
  expect(view.queryByText(/证据关系已由应用层校验/)).toBeNull();
  expect(view.queryByText(/不是模型自由生成/)).toBeNull();
  await fireEvent.press(view.getAllByLabelText("关闭")[0]);
  expect(onClose).toHaveBeenCalled();
});

test("引用对象当前不可用时回退快照并隐藏修订入口", async () => {
  const api = knowledgeAgentApi as jest.Mocked<typeof knowledgeAgentApi>;
  (api.getEntryCurrent as jest.Mock).mockRejectedValue({ status: 404 });
  const onRevise = jest.fn();
  const view = await render(
    <CitationSheet
      citation={citation(9, {
        entryTitle: "已删除知识",
        projectName: "新房装修",
        nodePath: "施工",
        sourceTitle: "旧来源.md",
        quote: "历史核验原文片段",
      })}
      revisionTargets={[
        {
          entryId: 9,
          entryTitle: "已删除知识",
          projectId: 1,
          projectName: "新房装修",
          nodePath: "施工",
        },
      ]}
      sourceRunId={9}
      onRevise={onRevise}
      onClose={jest.fn()}
    />,
    { wrapper },
  );
  await waitFor(() => expect(view.getByText("该知识当前不可用")).toBeOnTheScreen());
  // 历史快照仍可核验阅读
  expect(view.getByText(/历史核验原文片段/)).toBeOnTheScreen();
  expect(view.queryByText("开始修订")).toBeNull();
  expect(onRevise).not.toHaveBeenCalled();
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
  expect(
    view.getByText(/正式知识、你提供的信息与 AI 通用能力/),
  ).toBeOnTheScreen();
  expect(view.queryByText(/当前只读取/)).toBeNull();
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

test("确认回执在目录推荐或关系判断未完成时明确提示", async () => {
  const view = await render(
    <DraftReceiptCard
      draft={draftFixture({
        status: "confirmed",
        confirmedCandidateId: 99,
        routingStatus: "pending",
        relationStatus: "pending",
      })}
    />,
    { wrapper },
  );
  expect(view.getByText(/已创建待确认知识/)).toBeOnTheScreen();
  expect(view.getByText(/目录推荐或关系判断尚未完成/)).toBeOnTheScreen();
  expect(view.getAllByText(/尚未写入正式知识/).length).toBeGreaterThan(0);
  await view.unmount();
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

test("修订草稿卡区分 AI 建议语义并展示目标、变化字段与来源数量", async () => {
  const onEdit = jest.fn();
  const view = await render(
    <RevisionDraftCard
      draft={revisionDraftFixture()}
      confirming={false}
      onEdit={onEdit}
      onConfirm={jest.fn()}
      onCancel={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText("可编辑知识草稿")).toBeOnTheScreen();
  expect(view.getByText("AI 建议 · 待确认")).toBeOnTheScreen();
  expect(view.getByText(/变化字段：2 项/)).toBeOnTheScreen();
  expect(view.getByText(/1 条核验证据/)).toBeOnTheScreen();
  // 不出现 Candidate 回执语义
  expect(view.queryByText("已创建待确认知识")).toBeNull();
  await fireEvent.press(view.getByText("编辑并检查"));
  expect(onEdit).toHaveBeenCalled();
});

test("修订草稿生成过程卡可取消且不宣称已修改", async () => {
  const onCancel = jest.fn();
  const view = await render(
    <RevisionProcessCard
      run={run(40, "processing", null, { runKind: "entry_revision" })}
      cancelling={false}
      onCancel={onCancel}
    />,
    { wrapper },
  );
  expect(view.getByText("正在生成修订草稿")).toBeOnTheScreen();
  expect(view.getByText(/确认前不会修改正式知识/)).toBeOnTheScreen();
  await fireEvent.press(view.getByLabelText("取消修订"));
  expect(onCancel).toHaveBeenCalled();
});

test("applied 回执展示正式知识已更新、版本与撤销；undone 收敛为已撤销", async () => {
  const onUndo = jest.fn();
  const appliedView = await render(
    <RevisionReceiptCard
      draft={revisionDraftFixture({
        status: "applied",
        execution: {
          id: 9,
          draftId: 30,
          entryId: 1,
          status: "applied",
          beforeVersionNumber: 1,
          afterVersionNumber: 2,
          addedEvidenceCount: 1,
          error: null,
          undoneAt: null,
          createdAt: "2026-08-29T10:00:00Z",
          updatedAt: "2026-08-29T10:00:00Z",
        },
      })}
      undoing={false}
      undoError={null}
      undoRetryable={false}
      onViewDiff={jest.fn()}
      onUndo={onUndo}
      onRetryUndo={jest.fn()}
    />,
    { wrapper },
  );
  expect(appliedView.getByText("正式知识已更新")).toBeOnTheScreen();
  expect(appliedView.getByText(/已更新至版本 2/)).toBeOnTheScreen();
  await fireEvent.press(appliedView.getByText("撤销"));
  expect(onUndo).toHaveBeenCalled();

  const undoneView = await render(
    <RevisionReceiptCard
      draft={revisionDraftFixture({
        status: "undone",
        execution: {
          id: 9,
          draftId: 30,
          entryId: 1,
          status: "undone",
          beforeVersionNumber: 1,
          afterVersionNumber: 2,
          addedEvidenceCount: 1,
          error: null,
          undoneAt: "2026-08-29T10:01:00Z",
          createdAt: "2026-08-29T10:00:00Z",
          updatedAt: "2026-08-29T10:01:00Z",
        },
      })}
      undoing={false}
      undoError={null}
      undoRetryable={false}
      onViewDiff={jest.fn()}
      onUndo={jest.fn()}
      onRetryUndo={jest.fn()}
    />,
    { wrapper },
  );
  expect(undoneView.getByText("操作已撤销 · 审计记录保留")).toBeOnTheScreen();
  expect(undoneView.getByText("查看恢复结果")).toBeOnTheScreen();
  expect(undoneView.queryByText("撤销")).toBeNull();
});

test("修订失败卡保留错误与重新修订入口，取消卡不再提供重试", async () => {
  const onRetry = jest.fn();
  const failedView = await render(
    <RevisionDraftFailedCard
      draft={revisionDraftFixture({ status: "failed", error: "模型不可用" })}
      onRetry={onRetry}
    />,
    { wrapper },
  );
  expect(failedView.getByText("模型不可用")).toBeOnTheScreen();
  await fireEvent.press(failedView.getByText("重新修订"));
  expect(onRetry).toHaveBeenCalled();

  const cancelledView = await render(
    <RevisionDraftFailedCard
      draft={revisionDraftFixture({ status: "cancelled" })}
      onRetry={jest.fn()}
    />,
    { wrapper },
  );
  expect(cancelledView.getByText("已取消修订")).toBeOnTheScreen();
  expect(cancelledView.queryByText("重新修订")).toBeNull();
});

test("修订指令 Sheet 空指令禁用提交，展示目标与后果", async () => {
  const onSubmit = jest.fn();
  const target: RevisionTarget = {
    entryId: 1,
    entryTitle: "闭水试验完成后再验收防水层",
    projectId: 1,
    projectName: "新房装修",
    nodePath: "施工 / 防水",
  };
  const view = await render(
    <RevisionInstructionSheet
      visible
      target={target}
      sourceRunId={5}
      submitting={false}
      error={null}
      onSubmit={onSubmit}
      onClose={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText("闭水试验完成后再验收防水层")).toBeOnTheScreen();
  expect(view.getByText(/确认前不会写入/)).toBeOnTheScreen();
  const submit = view.getByLabelText("提交修订");
  expect(submit.props.accessibilityState?.disabled).toBe(true);
  await fireEvent.changeText(view.getByLabelText("修订要求"), "补充适用条件");
  await fireEvent.press(view.getByLabelText("提交修订"));
  expect(onSubmit).toHaveBeenCalledWith(5, 1, "补充适用条件");
});

test("修订确认 Sheet 明确更新 1 条正式知识，确认中禁用主按钮", async () => {
  const onConfirm = jest.fn();
  const view = await render(
    <RevisionConfirmSheet
      visible
      draft={revisionDraftFixture()}
      confirming
      error={null}
      retryable={false}
      onConfirm={onConfirm}
      onClose={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText(/将更新 1 条正式知识并追加版本/)).toBeOnTheScreen();
  await fireEvent.press(view.getByText("确认中…"));
  expect(onConfirm).not.toHaveBeenCalled();
});

test("撤销 Sheet 二次确认，冲突时禁用撤销并展示原因", async () => {
  const onUndo = jest.fn();
  const view = await render(
    <RevisionUndoSheet
      visible
      draft={revisionDraftFixture({ status: "applied" })}
      undoing={false}
      error="知识后来发生了变化，不能自动撤销"
      retryable={false}
      onUndo={onUndo}
      onClose={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText("恢复操作前状态")).toBeOnTheScreen();
  expect(view.getByText(/审计记录不会删除/)).toBeOnTheScreen();
  expect(view.getByText(/知识后来发生了变化/)).toBeOnTheScreen();
  await fireEvent.press(view.getByText("撤销操作"));
  expect(onUndo).not.toHaveBeenCalled();
});

test("确认 Sheet 网络结果未知时保留原键重试入口", async () => {
  const onConfirm = jest.fn();
  const view = await render(
    <RevisionConfirmSheet
      visible
      draft={revisionDraftFixture()}
      confirming={false}
      error="连接超时，请检查网络后重试"
      retryable
      onConfirm={onConfirm}
      onClose={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText("结果未知，可重试")).toBeOnTheScreen();
  await fireEvent.press(view.getByText("重试确认"));
  expect(onConfirm).toHaveBeenCalled();
});

test("撤销 Sheet 网络结果未知时保留原键重试入口", async () => {
  const onUndo = jest.fn();
  const view = await render(
    <RevisionUndoSheet
      visible
      draft={revisionDraftFixture({ status: "applied" })}
      undoing={false}
      error="连接超时，请检查网络后重试"
      retryable
      onUndo={onUndo}
      onClose={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText("结果未知，可重试")).toBeOnTheScreen();
  await fireEvent.press(view.getByText("重试撤销"));
  expect(onUndo).toHaveBeenCalled();
});

test("applied 回执只对可重试错误展示重试撤销按钮", async () => {
  const retryableView = await render(
    <RevisionReceiptCard
      draft={revisionDraftFixture({
        status: "applied",
        execution: {
          id: 9,
          draftId: 30,
          entryId: 1,
          status: "applied",
          beforeVersionNumber: 1,
          afterVersionNumber: 2,
          addedEvidenceCount: 0,
          error: null,
          undoneAt: null,
          createdAt: "2026-08-29T10:00:00Z",
          updatedAt: "2026-08-29T10:00:00Z",
        },
      })}
      undoing={false}
      undoError="连接超时，请检查网络后重试"
      undoRetryable
      onViewDiff={jest.fn()}
      onUndo={jest.fn()}
      onRetryUndo={jest.fn()}
    />,
    { wrapper },
  );
  expect(retryableView.getByText("重试撤销")).toBeOnTheScreen();

  const conflictView = await render(
    <RevisionReceiptCard
      draft={revisionDraftFixture({
        status: "applied",
        execution: {
          id: 9,
          draftId: 30,
          entryId: 1,
          status: "applied",
          beforeVersionNumber: 1,
          afterVersionNumber: 2,
          addedEvidenceCount: 0,
          error: null,
          undoneAt: null,
          createdAt: "2026-08-29T10:00:00Z",
          updatedAt: "2026-08-29T10:00:00Z",
        },
      })}
      undoing={false}
      undoError="知识后来发生了变化，不能自动撤销；请到版本历史处理"
      undoRetryable={false}
      onViewDiff={jest.fn()}
      onUndo={jest.fn()}
      onRetryUndo={jest.fn()}
    />,
    { wrapper },
  );
  expect(conflictView.getByText(/知识后来发生了变化/)).toBeOnTheScreen();
  expect(conflictView.queryByText("重试撤销")).toBeNull();
});

test("全屏差异审阅按字段展示原内容/建议内容并可确认", async () => {
  const onConfirm = jest.fn();
  const view = await render(
    <RevisionDiffScreen
      visible
      draft={revisionDraftFixture()}
      onConfirm={onConfirm}
      onClose={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText("审阅完整差异")).toBeOnTheScreen();
  expect(view.getByText("核心内容")).toBeOnTheScreen();
  expect(view.getByText("旧内容")).toBeOnTheScreen();
  expect(view.getByText("新内容")).toBeOnTheScreen();
  expect(view.getByText("防水验收记录.md")).toBeOnTheScreen();
  await fireEvent.press(view.getByText("确认修改"));
  expect(onConfirm).toHaveBeenCalled();
});

test("已应用差异页不再提供确认修改按钮", async () => {
  const onConfirm = jest.fn();
  const view = await render(
    <RevisionDiffScreen
      visible
      draft={revisionDraftFixture({
        status: "applied",
        execution: {
          id: 9,
          draftId: 30,
          entryId: 1,
          status: "applied",
          beforeVersionNumber: 1,
          afterVersionNumber: 2,
          addedEvidenceCount: 0,
          error: null,
          undoneAt: null,
          createdAt: "2026-08-29T10:00:00Z",
          updatedAt: "2026-08-29T10:00:00Z",
        },
      })}
      onConfirm={onConfirm}
      onClose={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText("已应用到正式知识")).toBeOnTheScreen();
  expect(view.queryByText("确认修改")).toBeNull();
  expect(view.getByText(/已应用到正式知识，可返回查看回执/)).toBeOnTheScreen();
});

test("已撤销差异页展示审计保留说明", async () => {
  const view = await render(
    <RevisionDiffScreen
      visible
      draft={revisionDraftFixture({ status: "undone" })}
      onConfirm={jest.fn()}
      onClose={jest.fn()}
    />,
    { wrapper },
  );
  expect(view.getByText("操作已撤销 · 审计保留")).toBeOnTheScreen();
  expect(view.queryByText("确认修改")).toBeNull();
  expect(view.getByText(/已撤销，审计记录保留/)).toBeOnTheScreen();
});

test("修订编辑 Sheet 可编辑长正文与变更摘要并保存", async () => {
  const onSave = jest.fn();
  const view = await render(
    <RevisionEditSheet
      visible
      draft={revisionDraftFixture()}
      saving={false}
      error={null}
      onSave={onSave}
      onClose={jest.fn()}
    />,
    { wrapper },
  );
  const titleInput = view.getByLabelText("修订后标题");
  const contentInput = view.getByLabelText("修订后核心内容");
  await fireEvent.changeText(titleInput, "修订后标题");
  await fireEvent.changeText(contentInput, "修订后正文");
  await fireEvent.changeText(view.getByLabelText("变更摘要"), "修订摘要");
  await fireEvent.press(view.getByText("保存编辑"));
  expect(onSave).toHaveBeenCalledWith(
    expect.objectContaining({
      title: "修订后标题",
      content: "修订后正文",
      changeSummary: "修订摘要",
    }),
  );
});

test("对话内从引用发起修订并提交非空指令", async () => {
  const api = knowledgeAgentApi as jest.Mocked<typeof knowledgeAgentApi>;
  const answeredRun = run(5, "completed", {
    answer: "闭水试验通常持续 24 小时。",
    status: "completed",
    insufficientNote: null,
    citations: [
      citation(1, {
        entryTitle: "闭水试验时长",
        projectId: 1,
        projectName: "新房装修",
        scopeType: "project",
      }),
    ],
    conflicts: [],
  });
  api.listConversations.mockResolvedValue([conversation(1)]);
  api.getConversation.mockResolvedValue(conversation(1));
  api.listMessages.mockResolvedValue({
    items: [message(1, "user", 5, "闭水试验多久？"), message(2, "assistant", 5)],
    nextCursor: null,
    runs: [
      {
        ...answeredRun,
        scopeType: "project",
        projectId: 1,
        projectName: "新房装修",
      },
    ],
    candidateDrafts: [],
  });
  api.submitEntryRevision.mockResolvedValue({
    userMessage: message(3, "user", 40, "修订《闭水试验时长》：补充适用条件"),
    run: {
      ...run(40, "waiting", null),
      runKind: "entry_revision",
      sourceRunId: 5,
      targetEntryId: 1,
    },
    draft: revisionDraftFixture({ id: 40, operationRunId: 40 }),
  });
  (api.getEntryCurrent as jest.Mock).mockResolvedValue({
    id: 1,
    projectId: 1,
    nodeId: 1,
    nodeName: "施工",
    title: "闭水试验时长",
    content: "闭水试验通常持续 24 小时。",
    mainType: "method",
    infoNature: "advice",
    applicableCondition: null,
    note: null,
    createdAt: "2026-08-29T09:00:00Z",
    updatedAt: "2026-08-29T10:00:00Z",
  });

  const view = await render(<ConversationScreen />, { wrapper });
  // 打开引用 Sheet 并点击「开始修订」
  await waitFor(() =>
    expect(view.getByLabelText("查看引用：闭水试验时长")).toBeOnTheScreen(),
  );
  await fireEvent.press(view.getByLabelText("查看引用：闭水试验时长"));
  await waitFor(() => expect(view.getByText("开始修订")).toBeOnTheScreen());
  await fireEvent.press(view.getByText("开始修订"));

  // 指令 Sheet 出现，输入内容后提交
  await waitFor(() => expect(view.getByLabelText("修订要求")).toBeOnTheScreen());
  await fireEvent.changeText(view.getByLabelText("修订要求"), "补充适用条件");
  await fireEvent.press(view.getByLabelText("提交修订"));

  await waitFor(() => {
    expect(api.submitEntryRevision).toHaveBeenCalledWith("token", 1, {
      clientMessageId: expect.any(String),
      sourceRunId: 5,
      targetEntryId: 1,
      instruction: "补充适用条件",
    });
  });
});
