import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Animated, LayoutAnimation, Text } from "react-native";

import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import { EntryDetailSheet } from "@/src/knowledge-agent/components/EntryDetailSheet";
import { knowledgeAgentKeys } from "@/src/knowledge-agent/queryKeys";

const mockUseAuth = jest.fn(() => ({ token: "token", me: null }));
const mockRichTextRender = jest.fn();

jest.mock("@/src/auth", () => ({ useAuth: () => mockUseAuth() }));

jest.mock("@/src/knowledge-agent/components/RichText", () => {
  const React = jest.requireActual<typeof import("react")>("react");
  const { Text: NativeText } = jest.requireActual<typeof import("react-native")>("react-native");
  return {
    RichText: ({ children }: { children: string }) => {
      mockRichTextRender(children);
      return React.createElement(NativeText, null, children);
    },
  };
});

jest.mock("@/src/knowledge-agent/hooks/useReducedMotion", () => ({
  useReducedMotion: () => false,
}));

jest.mock("@/src/knowledge-agent/api", () => ({
  knowledgeAgentApi: {
    getEntryCurrent: jest.fn(),
    submitMessage: jest.fn(),
  },
}));

const api = knowledgeAgentApi as jest.Mocked<typeof knowledgeAgentApi>;
const clients: QueryClient[] = [];
type AnimationEnd = ((result: { finished: boolean }) => void) | undefined;

const ENTRY_DETAIL = {
  id: 8,
  projectId: 1,
  nodeId: 2,
  nodeName: "防水",
  title: "闭水试验",
  content: "当前正文采用正常阅读字号。",
  mainType: "knowledge" as const,
  infoNature: null,
  applicableCondition: null,
  note: null,
  createdAt: "2026-09-01T00:00:00Z",
  updatedAt: "2026-09-19T00:00:00Z",
  evidences: [
    { id: 3, sourceId: 4, sourceTitle: "施工说明", quote: "至少 24 小时" },
  ],
};

function mockParallelAnimations() {
  const callbacks: AnimationEnd[] = [];
  jest.spyOn(Animated, "parallel").mockImplementation(() => {
    return {
      start: jest.fn((callback?: AnimationEnd) => callbacks.push(callback)),
      stop: jest.fn(),
      reset: jest.fn(),
    } as unknown as Animated.CompositeAnimation;
  });
  return callbacks;
}

async function presentSheet(rendered: Awaited<ReturnType<typeof render>>, height = 320) {
  await fireEvent(rendered.getByTestId("bottom-sheet-modal"), "show");
  await fireEvent(rendered.getByTestId("bottom-sheet-panel"), "layout", {
    nativeEvent: { layout: { x: 0, y: 0, width: 390, height } },
  });
}

afterEach(async () => {
  cleanup();
  await act(async () => {
    await Promise.all(clients.map((client) => client.cancelQueries()));
  });
  clients.forEach((client) => client.clear());
  clients.length = 0;
  jest.clearAllMocks();
  jest.restoreAllMocks();
});

test("底部详情首次打开只读取单个 Entry，关闭不触发消息或模型", async () => {
  api.getEntryCurrent.mockResolvedValue(ENTRY_DETAIL);
  const onClose = jest.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  const rendered = await render(
    <QueryClientProvider client={client}>
      <EntryDetailSheet
        target={{
          entryId: 8,
          title: "闭水试验",
          projectName: "装修",
          nodePath: "施工 / 防水",
        }}
        onClose={onClose}
      />
    </QueryClientProvider>,
  );

  await waitFor(() => expect(rendered.getByText("当前正文采用正常阅读字号。")).toBeTruthy());
  expect(api.getEntryCurrent).toHaveBeenCalledTimes(1);
  expect(api.getEntryCurrent).toHaveBeenCalledWith("token", 8);
  expect(rendered.getByText("关联来源")).toBeTruthy();
  expect(rendered.queryByText("当前知识内容")).toBeNull();
  expect(
    rendered.queryByText("这里显示这条知识当前关联的来源，不代表本轮回答已经核验这些来源。"),
  ).toBeNull();
  await presentSheet(rendered);
  fireEvent.press(rendered.getByLabelText("关闭"));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(api.submitMessage).not.toHaveBeenCalled();
});

test("快速读取完成前不打开空弹层，正文就绪后一次呈现", async () => {
  let resolveEntry!: (value: typeof ENTRY_DETAIL) => void;
  api.getEntryCurrent.mockImplementation(
    () => new Promise((resolve) => {
      resolveEntry = resolve;
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  const rendered = await render(
    <QueryClientProvider client={client}>
      <EntryDetailSheet
        target={{ entryId: 8, title: "闭水试验", projectName: null, nodePath: null }}
        onClose={jest.fn()}
      />
    </QueryClientProvider>,
  );

  expect(rendered.queryByText("知识详情")).toBeNull();
  await act(async () => resolveEntry(ENTRY_DETAIL));
  await waitFor(() => expect(rendered.getByText("知识详情")).toBeTruthy());
  expect(rendered.getByText("当前正文采用正常阅读字号。")).toBeTruthy();
  expect(rendered.queryByText("正在读取当前知识…")).toBeNull();
});

test("已有内容入场收尾不额外提交，父级更新不重渲染详情查询树", async () => {
  const animationCallbacks = mockParallelAnimations();
  const layoutTransition = jest.spyOn(LayoutAnimation, "configureNext").mockImplementation();
  let resolveEntry!: (value: typeof ENTRY_DETAIL) => void;
  api.getEntryCurrent.mockImplementation(
    () => new Promise((resolve) => {
      resolveEntry = resolve;
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  client.setQueryData(knowledgeAgentKeys.entryCurrent(8), ENTRY_DETAIL);
  clients.push(client);
  const target = { entryId: 8, title: "闭水试验", projectName: null, nodePath: null };
  const onClose = jest.fn();
  const renderDetail = (marker: string) => (
    <QueryClientProvider client={client}>
      <EntryDetailSheet target={target} onClose={onClose} />
      <Text>{marker}</Text>
    </QueryClientProvider>
  );
  const rendered = await render(renderDetail("初始父级"));

  await waitFor(() => expect(rendered.getByText("当前正文采用正常阅读字号。")).toBeTruthy());
  mockUseAuth.mockClear();
  await rendered.rerender(renderDetail("更新后的父级"));
  expect(mockUseAuth).not.toHaveBeenCalled();

  await presentSheet(rendered, 260);
  expect(animationCallbacks).toHaveLength(1);
  mockUseAuth.mockClear();
  mockRichTextRender.mockClear();
  await act(async () => resolveEntry({ ...ENTRY_DETAIL }));
  await waitFor(() =>
    expect(client.getQueryState(knowledgeAgentKeys.entryCurrent(8))?.fetchStatus).toBe("idle"),
  );
  expect(mockUseAuth).not.toHaveBeenCalled();
  expect(mockRichTextRender).not.toHaveBeenCalled();

  await act(() => animationCallbacks[0]?.({ finished: true }));

  expect(mockRichTextRender).not.toHaveBeenCalled();
  expect(layoutTransition).not.toHaveBeenCalled();
});

test("慢读取在入场期间完成时保持 loading 快照，入场结束后再显示正文", async () => {
  const animationCallbacks = mockParallelAnimations();
  const layoutTransition = jest.spyOn(LayoutAnimation, "configureNext").mockImplementation();
  let resolveEntry!: (value: typeof ENTRY_DETAIL) => void;
  api.getEntryCurrent.mockImplementation(
    () => new Promise((resolve) => {
      resolveEntry = resolve;
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  const rendered = await render(
    <QueryClientProvider client={client}>
      <EntryDetailSheet
        target={{ entryId: 8, title: "闭水试验", projectName: null, nodePath: null }}
        onClose={jest.fn()}
      />
    </QueryClientProvider>,
  );

  await waitFor(() => expect(rendered.getByText("正在读取当前知识…")).toBeTruthy());
  await presentSheet(rendered, 180);
  expect(animationCallbacks).toHaveLength(1);
  await act(async () => resolveEntry(ENTRY_DETAIL));
  expect(rendered.getByText("正在读取当前知识…")).toBeTruthy();
  expect(rendered.queryByText("当前正文采用正常阅读字号。")).toBeNull();

  await act(() => animationCallbacks[0]?.({ finished: true }));
  await waitFor(() => expect(rendered.getByText("当前正文采用正常阅读字号。")).toBeTruthy());
  expect(rendered.queryByText("正在读取当前知识…")).toBeNull();
  expect(layoutTransition).toHaveBeenCalledTimes(1);
});

test("已有缓存刷新不会在入场期间替换内容或重播动画", async () => {
  const animationCallbacks = mockParallelAnimations();
  const layoutTransition = jest.spyOn(LayoutAnimation, "configureNext").mockImplementation();
  const refreshed = { ...ENTRY_DETAIL, content: "刷新后的更长正文。" };
  let resolveEntry!: (value: typeof ENTRY_DETAIL) => void;
  api.getEntryCurrent.mockImplementation(
    () => new Promise((resolve) => {
      resolveEntry = resolve;
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  client.setQueryData(knowledgeAgentKeys.entryCurrent(8), ENTRY_DETAIL);
  clients.push(client);
  const rendered = await render(
    <QueryClientProvider client={client}>
      <EntryDetailSheet
        target={{ entryId: 8, title: "闭水试验", projectName: null, nodePath: null }}
        onClose={jest.fn()}
      />
    </QueryClientProvider>,
  );

  await waitFor(() => expect(rendered.getByText("当前正文采用正常阅读字号。")).toBeTruthy());
  await presentSheet(rendered, 260);
  await act(async () => resolveEntry(refreshed));
  expect(rendered.getByText("当前正文采用正常阅读字号。")).toBeTruthy();
  expect(rendered.queryByText("刷新后的更长正文。")).toBeNull();
  expect(animationCallbacks).toHaveLength(1);

  await act(() => animationCallbacks[0]?.({ finished: true }));
  await waitFor(() => expect(rendered.getByText("刷新后的更长正文。")).toBeTruthy());
  expect(animationCallbacks).toHaveLength(1);
  expect(layoutTransition).toHaveBeenCalledTimes(1);
});

test("关闭后快速打开另一条知识时忽略旧请求的迟到结果", async () => {
  let resolveOldEntry!: (value: typeof ENTRY_DETAIL) => void;
  api.getEntryCurrent.mockImplementation((_token, entryId) => {
    if (entryId === 8) {
      return new Promise((resolve) => {
        resolveOldEntry = resolve;
      });
    }
    return Promise.resolve({
      ...ENTRY_DETAIL,
      id: 9,
      title: "新知识",
      content: "新知识正文。",
    });
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  const renderDetail = (entryId: number | null) => (
    <QueryClientProvider client={client}>
      <EntryDetailSheet
        target={
          entryId === null
            ? null
            : {
                entryId,
                title: entryId === 8 ? "闭水试验" : "新知识",
                projectName: null,
                nodePath: null,
              }
        }
        onClose={jest.fn()}
      />
    </QueryClientProvider>
  );
  const rendered = await render(renderDetail(8));
  await waitFor(() => expect(rendered.getByText("正在读取当前知识…")).toBeTruthy());

  await rendered.rerender(renderDetail(null));
  await rendered.rerender(renderDetail(9));
  await waitFor(() => expect(rendered.getByText("新知识正文。")).toBeTruthy());
  await act(async () => resolveOldEntry(ENTRY_DETAIL));

  expect(rendered.getByText("新知识正文。")).toBeTruthy();
  expect(rendered.queryByText("当前正文采用正常阅读字号。")).toBeNull();
  expect(api.getEntryCurrent).toHaveBeenCalledTimes(2);
});

test("详情网络失败可重试，当前不可访问不泄露正文", async () => {
  api.getEntryCurrent.mockRejectedValueOnce(new TypeError("Network request failed"));
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  const rendered = await render(
    <QueryClientProvider client={client}>
      <EntryDetailSheet
        target={{ entryId: 8, title: "闭水试验", projectName: null, nodePath: null }}
        onClose={jest.fn()}
      />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(rendered.getByText("当前知识读取失败")).toBeTruthy());
  expect(rendered.getByText("重试读取")).toBeTruthy();
  await presentSheet(rendered);

  api.getEntryCurrent.mockRejectedValueOnce(Object.assign(new Error("不存在"), { status: 404 }));
  await act(async () => {
    fireEvent.press(rendered.getByText("重试读取"));
  });
  await waitFor(() => expect(rendered.getByText("该知识当前不可访问")).toBeTruthy());
  expect(rendered.queryByText("重试读取")).toBeNull();
});
