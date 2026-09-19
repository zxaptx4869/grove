import { render } from "@testing-library/react-native";

import { ProcessCard } from "@/src/knowledge-agent/components/ProcessCard";
import type { KnowledgeRun } from "@/src/knowledge-agent/types";

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

test("过程卡展示真实 dialogue_stage", async () => {
  const rendered = await render(
    <ProcessCard
      run={processingRun("reading_entries")}
      scopeLabel="全部知识"
      cancelling={false}
      pollingError={null}
      cancelError={null}
      onCancel={jest.fn()}
      onRetryPolling={jest.fn()}
    />,
  );
  expect(rendered.getByText("正在读取知识")).toBeTruthy();
});

test("未知阶段稳定降级且网络错误不冒充服务端失败", async () => {
  const rendered = await render(
    <ProcessCard
      run={processingRun("future_stage")}
      scopeLabel="全部知识"
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
