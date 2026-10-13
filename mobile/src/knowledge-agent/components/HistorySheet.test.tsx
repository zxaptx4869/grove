import { cleanup, fireEvent, render, waitFor, within } from "@testing-library/react-native";
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
    action: null,
    onRetry: jest.fn(),
    onSelect: jest.fn(),
    onNew: jest.fn(),
    onRename: jest.fn(async () => ({ ok: true, message: null })),
    onDelete: jest.fn(async () => ({ ok: true, message: null })),
    onActionChange: jest.fn(),
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

test("不带时区的服务端时间按 UTC 解析：刚结束的对话显示刚刚", async () => {
  const now = Date.now();
  const naive = new Date(now - 20 * 1000);
  const iso = naive.toISOString().replace("Z", "");
  const rendered = await render(
    <HistorySheet {...props({ conversations: [{ ...conversation(1), lastActivityAt: iso }] })} />,
  );

  // 不补时区会按本地时间解析，东八区下显示成「8 小时前」
  expect(rendered.getByText("刚刚")).toBeTruthy();
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

test("长按某行弹出操作小窗，切换操作保持可用", async () => {
  const base = props({ conversations: [conversation(1)], activeConversationId: 1 });
  const rendered = await render(<HistorySheet {...base} />);

  await fireEvent.press(rendered.getByLabelText("切换到对话：对话 1"));
  expect(base.onSelect).toHaveBeenCalledWith(1);

  await fireEvent(rendered.getByLabelText("切换到对话：对话 1"), "longPress");
  expect(base.onActionChange).toHaveBeenCalledWith({
    type: "menu",
    conversation: expect.objectContaining({ id: 1 }),
  });
});

test("读屏自定义操作可直接触发重命名与删除", async () => {
  const base = props({ conversations: [conversation(1)] });
  const rendered = await render(<HistorySheet {...base} />);
  const row = rendered.getByLabelText("切换到对话：对话 1");

  await fireEvent(row, "accessibilityAction", { nativeEvent: { actionName: "rename" } });
  expect(base.onActionChange).toHaveBeenCalledWith({
    type: "rename",
    conversation: expect.objectContaining({ id: 1 }),
  });

  await fireEvent(row, "accessibilityAction", { nativeEvent: { actionName: "delete" } });
  expect(base.onActionChange).toHaveBeenCalledWith({
    type: "delete",
    conversation: expect.objectContaining({ id: 1 }),
  });
});

test("操作小窗提供重命名、删除与取消入口", async () => {
  const base = props({
    conversations: [conversation(1)],
    action: { type: "menu", conversation: conversation(1) },
  });
  const rendered = await render(<HistorySheet {...base} />);

  await fireEvent.press(rendered.getByLabelText("重命名"));
  expect(base.onActionChange).toHaveBeenCalledWith({
    type: "rename",
    conversation: expect.objectContaining({ id: 1 }),
  });

  await fireEvent.press(rendered.getByLabelText("删除"));
  expect(base.onActionChange).toHaveBeenCalledWith({
    type: "delete",
    conversation: expect.objectContaining({ id: 1 }),
  });

  await fireEvent.press(rendered.getByLabelText("取消"));
  expect(base.onActionChange).toHaveBeenCalledWith(null);
});

test("重命名与删除表单放在独立底部弹层，不占用历史列表顶部", async () => {
  const rendered = await render(
    <HistorySheet
      {...props({
        conversations: [conversation(1)],
        action: { type: "rename", conversation: conversation(1) },
      })}
    />,
  );

  const bottomSheet = rendered.getByTestId("bottom-sheet-panel");
  expect(within(bottomSheet).getByTestId("conversation-rename-input")).toBeTruthy();
});

test("重命名非法输入就地提示且不发请求", async () => {
  const base = props({
    conversations: [conversation(1)],
    action: { type: "rename", conversation: conversation(1) },
  });
  const rendered = await render(<HistorySheet {...base} />);

  await fireEvent.changeText(rendered.getByTestId("conversation-rename-input"), "   ");
  await fireEvent.press(rendered.getByLabelText("保存"));

  await waitFor(() => expect(rendered.getByText("标题不能为空")).toBeTruthy());
  expect(base.onRename).not.toHaveBeenCalled();

  await fireEvent.changeText(
    rendered.getByTestId("conversation-rename-input"),
    "长".repeat(256),
  );
  await fireEvent.press(rendered.getByLabelText("保存"));
  await waitFor(() =>
    expect(rendered.getByText("标题不能超过 255 个字符")).toBeTruthy(),
  );
  expect(base.onRename).not.toHaveBeenCalled();
});

test("重命名成功后关闭操作区", async () => {
  const onRename = jest.fn(async () => ({ ok: true, message: null }));
  const onActionChange = jest.fn();
  const rendered = await render(
    <HistorySheet
      {...props({
        conversations: [conversation(1)],
        action: { type: "rename", conversation: conversation(1) },
        onRename,
        onActionChange,
      })}
    />,
  );

  await fireEvent.changeText(rendered.getByTestId("conversation-rename-input"), "施工笔记");
  await fireEvent.press(rendered.getByLabelText("保存"));

  await waitFor(() => expect(onRename).toHaveBeenCalledWith(1, "施工笔记"));
  await waitFor(() => expect(onActionChange).toHaveBeenCalledWith(null));
});

test("重命名失败就地提示并保留操作区", async () => {
  const onRename = jest.fn(async () => ({ ok: false, message: "标题已被其他端修改" }));
  const rendered = await render(
    <HistorySheet
      {...props({
        conversations: [conversation(1)],
        action: { type: "rename", conversation: conversation(1) },
        onRename,
      })}
    />,
  );

  await fireEvent.press(rendered.getByLabelText("保存"));

  await waitFor(() => expect(rendered.getByText("标题已被其他端修改")).toBeTruthy());
  expect(rendered.getByTestId("conversation-rename-input")).toBeTruthy();
});

test("删除二次确认说明内容保留，取消不发请求", async () => {
  const onDelete = jest.fn(async () => ({ ok: true, message: null }));
  const onActionChange = jest.fn();
  const rendered = await render(
    <HistorySheet
      {...props({
        conversations: [conversation(1)],
        action: { type: "delete", conversation: conversation(1) },
        onDelete,
        onActionChange,
      })}
    />,
  );

  expect(rendered.getByText(/将从列表移除，对话内容保留/)).toBeTruthy();

  await fireEvent.press(rendered.getByLabelText("取消"));
  expect(onActionChange).toHaveBeenCalledWith(null);
  expect(onDelete).not.toHaveBeenCalled();
});

test("删除冲突时就地提示需等待完成", async () => {
  const onDelete = jest.fn(async () => ({
    ok: false,
    message: "对话存在进行中的问答，请等待完成或取消后再删除",
  }));
  const rendered = await render(
    <HistorySheet
      {...props({
        conversations: [conversation(1)],
        action: { type: "delete", conversation: conversation(1) },
        onDelete,
      })}
    />,
  );

  await fireEvent.press(rendered.getByLabelText("确认删除"));

  await waitFor(() =>
    expect(rendered.getByText(/对话存在进行中的问答/)).toBeTruthy(),
  );
  expect(onDelete).toHaveBeenCalledWith(1);
});
