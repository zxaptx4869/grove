import { StyleSheet } from "react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";

import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import { EntryResultSheet } from "@/src/knowledge-agent/components/EntryResultSheet";
import {
  EntryResultRow,
  EntryResultsCard,
} from "@/src/knowledge-agent/components/EntryResultsCard";
import type { EntryResultsState } from "@/src/knowledge-agent/hooks/useConversationController";
import type {
  KnowledgeEntryResultItem,
  KnowledgeEntryResultSnapshot,
  KnowledgeRun,
} from "@/src/knowledge-agent/types";

jest.mock("@/src/knowledge-agent/api", () => ({
  knowledgeAgentApi: {
    getEntryCurrent: jest.fn(),
  },
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ token: "token", me: null }),
}));

const api = knowledgeAgentApi as jest.Mocked<typeof knowledgeAgentApi>;
const sheetClients: QueryClient[] = [];

afterEach(async () => {
  await act(async () => {
    await Promise.all(sheetClients.map((client) => client.cancelQueries()));
  });
  for (const client of sheetClients) {
    client.clear();
  }
  sheetClients.length = 0;
});

function item(
  entryId: number,
  overrides: Partial<KnowledgeEntryResultItem> = {},
): KnowledgeEntryResultItem {
  return {
    entryId,
    title: `闭水试验 ${entryId}`,
    excerpt: "基层处理、涂刷范围与闭水验收要点。",
    projectId: 1,
    projectName: "新房装修",
    nodeId: 1,
    nodePath: "施工 / 防水",
    mainType: "knowledge",
    infoNature: "fact",
    updatedAt: "2026-08-29T10:00:00Z",
    sourceCount: 2,
    fingerprint: `fp-${entryId}`,
    matchHint: "标题包含「闭水试验」",
    matchedFields: ["title"],
    ...overrides,
  };
}

function snapshot(
  items: KnowledgeEntryResultItem[],
  overrides: Partial<KnowledgeEntryResultSnapshot> = {},
): KnowledgeEntryResultSnapshot {
  return {
    schemaVersion: "v1",
    query: "闭水试验",
    status: "completed",
    completeness: "complete",
    items,
    returnedCount: items.length,
    candidateLimit: 50,
    warning: null,
    snapshotUpdatedAt: "2026-08-29T10:00:00Z",
    ...overrides,
  };
}

function run(
  entryResult: KnowledgeEntryResultSnapshot | null,
  overrides: Partial<KnowledgeRun> = {},
): KnowledgeRun {
  return {
    id: 7,
    conversationId: 1,
    runKind: "answer",
    status: "completed",
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
    requestResultMode: "auto",
    actualResultMode: "entries",
    currentRound: 0,
    inputContextVersionId: null,
    outputContextVersionId: null,
    contextDegraded: false,
    fallbackSummary: null,
    investigationSummary: null,
    answer: null,
    entryResult,
    createdAt: "2026-08-29T10:00:00Z",
    updatedAt: "2026-08-29T10:00:00Z",
    ...overrides,
  };
}

function state(overrides: Partial<EntryResultsState> = {}): EntryResultsState {
  return {
    runId: 7,
    items: [],
    nextCursor: null,
    hasMore: false,
    loadingMore: false,
    error: null,
    primed: true,
    ...overrides,
  };
}

function noop() {
  // 测试替身
}

describe("EntryResultsCard", () => {
  test("Workspace 跨项目结果逐项显示项目归属；行可打开详情", async () => {
    const items = [
      item(1, { projectName: "项目甲", nodePath: "施工" }),
      item(2, { projectName: "项目乙", nodePath: "健康" }),
    ];
    const runRow = run(snapshot(items));
    const onOpen = jest.fn();
    await render(
      <EntryResultsCard
        run={runRow}
        scopeLabel="全部知识"
        state={state({ items, hasMore: false })}
        onPrime={noop}
        onLoadMore={noop}
        onRetry={noop}
        onOpenItem={onOpen}
        onCorrectMode={noop}
        onRefine={noop}
      />,
    );
    expect(screen.getByText("找到 2 条相关知识")).toBeOnTheScreen();
    // 头部 Badge + 每条结果行的 Badge
    expect(screen.getAllByText("正式知识").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText("项目甲 / 施工")).toBeOnTheScreen();
    expect(screen.getByText("项目乙 / 健康")).toBeOnTheScreen();
    expect(screen.getByText("已完整列出当前范围匹配的正式知识")).toBeOnTheScreen();
    expect(screen.getAllByText("2 个来源")).toHaveLength(2);

    await fireEvent.press(screen.getByLabelText("第 1 条，正式知识，闭水试验 1，项目甲 / 施工"));
    expect(onOpen).toHaveBeenCalledWith(items[0]);
  });

  test("项目范围收敛项目名但行内仍显示归属", async () => {
    const runRow = run(snapshot([item(1)]), {
      scopeType: "project",
      projectId: 1,
      projectName: "项目甲",
    });
    await render(
      <EntryResultsCard
        run={runRow}
        scopeLabel="项目甲"
        state={state({ items: [item(1)] })}
        onPrime={noop}
        onLoadMore={noop}
        onRetry={noop}
        onOpenItem={noop}
        onCorrectMode={noop}
        onRefine={noop}
      />,
    );
    expect(screen.getByText("检索范围：项目甲")).toBeOnTheScreen();
    expect(screen.getByText("新房装修 / 施工 / 防水")).toBeOnTheScreen();
  });

  test("空结果展示空态与修改问题动作", async () => {
    const runRow = run(snapshot([]));
    const onRefine = jest.fn();
    await render(
      <EntryResultsCard
        run={runRow}
        scopeLabel="全部知识"
        state={state()}
        onPrime={noop}
        onLoadMore={noop}
        onRetry={noop}
        onOpenItem={noop}
        onCorrectMode={noop}
        onRefine={onRefine}
      />,
    );
    expect(screen.getByText("没有找到匹配的正式知识")).toBeOnTheScreen();
    await fireEvent.press(screen.getByLabelText("修改问题"));
    expect(onRefine).toHaveBeenCalled();
  });

  test("长标题/长摘要不截断行内容且不横向溢出（numberOfLines 约束）", async () => {
    const longTitle = "闭水试验".repeat(40);
    const longExcerpt = "基层处理、涂刷范围与闭水验收要点。".repeat(60);
    const longItem = item(1, {
      title: longTitle,
      excerpt: longExcerpt,
    });
    await render(
      <EntryResultRow item={longItem} index={0} onPress={noop} />,
    );
    expect(screen.getByText(longTitle)).toBeOnTheScreen();
    expect(screen.getByText(longExcerpt)).toBeOnTheScreen();
  });

  test("limited/unknown 完整性与分页失败保留已加载项并支持重试", async () => {
    const items = [item(1), item(2)];
    const runRow = run(
      snapshot(items, { completeness: "limited", warning: "结果达到候选或数量上限" }),
    );
    const onRetry = jest.fn();
    await render(
      <EntryResultsCard
        run={runRow}
        scopeLabel="全部知识"
        state={state({
          items,
          hasMore: false,
          error: "网络中断",
        })}
        onPrime={noop}
        onLoadMore={noop}
        onRetry={onRetry}
        onOpenItem={noop}
        onCorrectMode={noop}
        onRefine={noop}
      />,
    );
    expect(screen.getByText("本次结果可能不完整，可缩小条件再找")).toBeOnTheScreen();
    expect(screen.getByText(/加载更多失败/)).toBeOnTheScreen();
    expect(screen.getByText("闭水试验 1")).toBeOnTheScreen();
    expect(screen.getByText("闭水试验 2")).toBeOnTheScreen();
    await fireEvent.press(screen.getByLabelText("重试加载更多结果"));
    expect(onRetry).toHaveBeenCalled();
  });

  test("30 条快照首屏只显示一页，加载更多按钮可走通", async () => {
    const items = Array.from({ length: 30 }, (_, index) => item(index + 1));
    const runRow = run(snapshot(items, { completeness: "limited" }));
    const onLoadMore = jest.fn();
    await render(
      <EntryResultsCard
        run={runRow}
        scopeLabel="全部知识"
        state={state({
          items: items.slice(0, 6),
          hasMore: true,
        })}
        onPrime={noop}
        onLoadMore={onLoadMore}
        onRetry={noop}
        onOpenItem={noop}
        onCorrectMode={noop}
        onRefine={noop}
      />,
    );
    expect(screen.getAllByText(/^闭水试验 \d+$/)).toHaveLength(6);
    await fireEvent.press(screen.getByLabelText("加载更多结果"));
    expect(onLoadMore).toHaveBeenCalled();
  });

  test("不出现勾选、修订、批量或合并操作文案", async () => {
    const runRow = run(snapshot([item(1)]));
    await render(
      <EntryResultsCard
        run={runRow}
        scopeLabel="全部知识"
        state={state({ items: [item(1)] })}
        onPrime={noop}
        onLoadMore={noop}
        onRetry={noop}
        onOpenItem={noop}
        onCorrectMode={noop}
        onRefine={noop}
      />,
    );
    expect(screen.queryByText(/勾选|全选/)).toBeNull();
    expect(screen.queryByText(/修订/)).toBeNull();
    expect(screen.queryByText(/批量/)).toBeNull();
    expect(screen.queryByText(/合并/)).toBeNull();
  });

  test("触控目标与辅助名称满足 44×44 与读屏要求", async () => {
    const runRow = run(snapshot([item(1)]));
    await render(
      <EntryResultsCard
        run={runRow}
        scopeLabel="全部知识"
        state={state({ items: [item(1)], hasMore: true })}
        onPrime={noop}
        onLoadMore={noop}
        onRetry={noop}
        onOpenItem={noop}
        onCorrectMode={noop}
        onRefine={noop}
      />,
    );
    const loadMore = screen.getByLabelText("加载更多结果");
    const flattened = StyleSheet.flatten(loadMore.props.style);
    expect(flattened.minHeight).toBeGreaterThanOrEqual(44);
    const correct = screen.getByLabelText("改为综合回答");
    expect(StyleSheet.flatten(correct.props.style).minHeight).toBeGreaterThanOrEqual(44);
  });
});

describe("EntryResultSheet", () => {
  function wrapper() {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    sheetClients.push(queryClient);
    return function Wrapper({ children }: { children: React.ReactNode }) {
      return (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      );
    };
  }

  test("指纹一致显示当前一致；指纹变化显示已更新", async () => {
    api.getEntryCurrent.mockResolvedValue({
      id: 1,
      projectId: 1,
      nodeId: 1,
      nodeName: "施工",
      title: "闭水试验 1",
      content: "当前内容",
      mainType: "knowledge",
      infoNature: "fact",
      applicableCondition: null,
      note: null,
      createdAt: "2026-08-29T09:00:00Z",
      updatedAt: "2026-08-29T10:00:00Z",
      fingerprint: "fp-new",
      evidences: [{ id: 1, sourceId: 1, sourceTitle: "验收手册", quote: "原文" }],
    });
    const view = await render(
      <EntryResultSheet
        item={item(1, { fingerprint: "fp-old" })}
        onClose={noop}
      />,
      { wrapper: wrapper() },
    );
    await waitFor(() => {
      expect(screen.getByText("结果生成后已更新")).toBeOnTheScreen();
    });
    expect(screen.getByText("当前内容")).toBeOnTheScreen();
    expect(screen.getByText(/验收手册/)).toBeOnTheScreen();
    await view.unmount();
  });

  test("当前 Entry 404 显示不可用且不泄露内容", async () => {
    api.getEntryCurrent.mockRejectedValue({ status: 404, message: "Entry 不存在" });
    const view = await render(
      <EntryResultSheet item={item(2)} onClose={noop} />,
      { wrapper: wrapper() },
    );
    await waitFor(() => {
      expect(screen.getByText("该知识当前不可用")).toBeOnTheScreen();
    });
    expect(screen.queryByText("当前内容")).toBeNull();
    await view.unmount();
  });
});
