import { cleanup, fireEvent, render } from "@testing-library/react-native";
import { HistorySheet } from "@/src/knowledge-agent/components/HistorySheet";
import type { KnowledgeConversation } from "@/src/knowledge-agent/types";

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
    lastActivityAt: "2026-09-20T08:00:00Z",
    createdAt: "2026-09-20T08:00:00Z",
  };
}

function props(overrides: Partial<React.ComponentProps<typeof HistorySheet>> = {}) {
  return {
    visible: true,
    conversations: [] as KnowledgeConversation[],
    activeConversationId: null,
    loading: false,
    error: null,
    onRetry: jest.fn(),
    onSelect: jest.fn(),
    onNew: jest.fn(),
    onClose: jest.fn(),
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  jest.clearAllMocks();
});

test("历史未加载或加载失败时仍可立即新建对话", async () => {
  const loadingProps = props({ conversations: undefined, loading: true });
  const loading = await render(<HistorySheet {...loadingProps} />);
  await fireEvent.press(loading.getByLabelText("新建对话"));
  expect(loadingProps.onNew).toHaveBeenCalledTimes(1);

  const failedProps = props({ conversations: undefined, error: "网络中断" });
  await loading.rerender(<HistorySheet {...failedProps} />);
  await fireEvent.press(loading.getByLabelText("新建对话"));
  await fireEvent.press(loading.getByLabelText("重试加载历史"));
  expect(failedProps.onNew).toHaveBeenCalledTimes(1);
  expect(failedProps.onRetry).toHaveBeenCalledTimes(1);
});

test("大量历史摘要使用有限首批的非嵌套虚拟列表", async () => {
  const conversations = Array.from({ length: 240 }, (_, index) => conversation(index + 1));
  const rendered = await render(<HistorySheet {...props({ conversations })} />);
  const list = rendered.getByTestId("conversation-history-list");
  expect(list.props.data).toHaveLength(240);
  expect(list.props.initialNumToRender).toBe(12);
  expect(list.props.maxToRenderPerBatch).toBe(12);
  expect(list.props.windowSize).toBe(5);
  expect(list.props.removeClippedSubviews).toBe(true);
});
