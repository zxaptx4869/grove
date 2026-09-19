import { cleanup, fireEvent, render } from "@testing-library/react-native";

import { ProcessCard } from "@/src/knowledge-agent/components/ProcessCard";
import type { KnowledgeRun } from "@/src/knowledge-agent/types";

const mockUseReducedMotion = jest.fn(() => false);

jest.mock("@/src/knowledge-agent/hooks/useReducedMotion", () => ({
  useReducedMotion: () => mockUseReducedMotion(),
}));

function processingRun(stage: string | null): KnowledgeRun {
  return {
    id: 1,
    conversationId: 1,
    status: "processing",
    currentStep: "dialogue_loop",
    scopeType: "workspace",
    projectId: null,
    projectName: null,
    userMessageId: 1,
    assistantMessageId: 2,
    cancelRequested: false,
    error: null,
    requestContextMode: "auto",
    contextDecision: null,
    standaloneQuery: null,
    topicLabel: null,
    answer: null,
    dialogueLoopStatus: "processing",
    dialogueStage: stage,
    dialogueBlocks: [],
    canContinue: false,
    continuation: null,
    createdAt: "2026-09-19T10:00:00Z",
    updatedAt: "2026-09-19T10:00:00Z",
  };
}

afterEach(() => {
  cleanup();
  mockUseReducedMotion.mockReturnValue(false);
});

test("过程卡展示真实 dialogue_stage", async () => {
  const onCancel = jest.fn();
  const rendered = await render(
    <ProcessCard
      run={processingRun("reading_entries")}
      cancelling={false}
      pollingError={null}
      cancelError={null}
      onCancel={onCancel}
      onRetryPolling={jest.fn()}
    />,
  );
  expect(rendered.getByText("正在读取知识")).toBeTruthy();
  expect(rendered.queryByText("范围：全部知识")).toBeNull();
  fireEvent.press(rendered.getByLabelText("停止当前回答"));
  expect(onCancel).toHaveBeenCalledTimes(1);
});

test("取消中禁止重复操作，取消失败保留轻量重试入口", async () => {
  const onCancel = jest.fn();
  const cancelling = await render(
    <ProcessCard
      run={processingRun("querying")}
      cancelling
      pollingError={null}
      cancelError={null}
      onCancel={onCancel}
      onRetryPolling={jest.fn()}
    />,
  );
  fireEvent.press(cancelling.getByLabelText("正在取消回答"));
  expect(onCancel).not.toHaveBeenCalled();
  await cancelling.unmount();

  const failed = await render(
    <ProcessCard
      run={processingRun("querying")}
      cancelling={false}
      pollingError={null}
      cancelError="网络不可用"
      onCancel={onCancel}
      onRetryPolling={jest.fn()}
    />,
  );
  expect(failed.getByText("取消请求未完成")).toBeTruthy();
  fireEvent.press(failed.getByText("重试取消"));
  expect(onCancel).toHaveBeenCalledTimes(1);
});

test("未知阶段稳定降级且网络错误不冒充服务端失败", async () => {
  const rendered = await render(
    <ProcessCard
      run={processingRun("future_stage")}
      cancelling={false}
      pollingError="连接超时"
      cancelError={null}
      onCancel={jest.fn()}
      onRetryPolling={jest.fn()}
    />,
  );
  expect(rendered.getByText("正在处理")).toBeTruthy();
  expect(rendered.getByText("连接中断，服务端状态未知")).toBeTruthy();
});

test("系统减少动态效果时以静态状态图标替代过程动效", async () => {
  mockUseReducedMotion.mockReturnValue(true);
  const rendered = await render(
    <ProcessCard
      run={processingRun("querying")}
      cancelling={false}
      pollingError={null}
      cancelError={null}
      onCancel={jest.fn()}
      onRetryPolling={jest.fn()}
    />,
  );
  expect(rendered.getByTestId("agent-stage-static")).toBeTruthy();
  expect(rendered.queryByTestId("agent-stage-spinner")).toBeNull();
});
