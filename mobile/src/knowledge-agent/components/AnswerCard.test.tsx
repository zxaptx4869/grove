import { act, cleanup, fireEvent, render } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import { AnswerCard } from "@/src/knowledge-agent/components/AnswerCard";
import type { KnowledgeRun } from "@/src/knowledge-agent/types";

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ token: "token", me: null }),
}));

jest.mock("@/src/knowledge-agent/api", () => ({
  knowledgeAgentApi: {
    getEntryCurrent: jest.fn(),
    submitMessage: jest.fn(),
  },
}));

const api = knowledgeAgentApi as jest.Mocked<typeof knowledgeAgentApi>;
const clients: QueryClient[] = [];

afterEach(async () => {
  cleanup();
  await act(async () => {
    await Promise.all(clients.map((client) => client.cancelQueries()));
  });
  clients.forEach((client) => client.clear());
  clients.length = 0;
  jest.clearAllMocks();
});

function run(overrides: Partial<KnowledgeRun> = {}): KnowledgeRun {
  return {
    id: 1,
    conversationId: 1,
    status: "completed",
    currentStep: null,
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
    answer: { answer: "扁平答案", status: "completed" },
    dialogueLoopStatus: "completed",
    dialogueStage: null,
    dialogueBlocks: [],
    canContinue: false,
    continuation: null,
    createdAt: "2026-09-19T10:00:00Z",
    updatedAt: "2026-09-19T10:00:00Z",
    ...overrides,
  };
}

async function renderCard(
  value: KnowledgeRun,
  props: { onContinue?: jest.Mock; onRetry?: jest.Mock } = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  const onContinue = props.onContinue ?? jest.fn();
  const onRetry = props.onRetry ?? jest.fn();
  const onOpenEntry = jest.fn();
  const rendered = await render(
    <QueryClientProvider client={client}>
      <AnswerCard
        run={value}
        scopeLabel="全部知识"
        canContinue={value.canContinue}
        onContinue={onContinue}
        onRetry={onRetry}
        onOpenEntry={onOpenEntry}
      />
    </QueryClientProvider>,
  );
  return { ...rendered, onContinue, onRetry, onOpenEntry };
}

test("按服务端块顺序展示且不重复扁平答案", async () => {
  const rendered = await renderCard(
    run({
      dialogueBlocks: [
        { kind: "text", text: "第一段" },
        { kind: "statistic", label: "数量", value: 3 },
        { kind: "candidate", text: "第三段候选" },
      ],
    }),
  );
  const tree = JSON.stringify(rendered.toJSON());
  expect(tree.indexOf("第一段")).toBeLessThan(tree.indexOf("数量"));
  expect(tree.indexOf("数量")).toBeLessThan(tree.indexOf("第三段候选"));
  expect(rendered.queryByText("扁平答案")).toBeNull();
  expect(rendered.getByText("AI 修改建议 / 候选稿 · 未应用")).toBeTruthy();
});

test("知识列表保持紧凑层级并只把明确 Entry 交给详情", async () => {
  const rendered = await renderCard(
    run({
      dialogueBlocks: [
        {
          kind: "list",
          resultType: "entries",
          items: [
            {
              entryId: 8,
              title: "闭水试验",
              projectName: "装修",
              nodePath: "施工 / 防水",
              summary: "这是一个很长的正文摘要，只允许在列表中显示一行。",
              relevanceLevel: "indirect",
              relevanceReason: "用于补充防水施工的验收背景",
            },
          ],
        },
      ],
    }),
  );
  expect(api.getEntryCurrent).not.toHaveBeenCalled();
  expect(rendered.getByText("装修 / 施工 / 防水")).toBeTruthy();
  expect(
    rendered.queryByText("这是一个很长的正文摘要，只允许在列表中显示一行。"),
  ).toBeNull();
  expect(rendered.getByText("间接相关：用于补充防水施工的验收背景")).toBeTruthy();
  await act(async () => {
    fireEvent.press(rendered.getByLabelText("第 1 条，闭水试验，打开知识详情"));
  });
  expect(rendered.onOpenEntry).toHaveBeenCalledWith({
    entryId: 8,
    title: "闭水试验",
    projectName: "装修",
    nodePath: "施工 / 防水",
  });
  expect(api.getEntryCurrent).not.toHaveBeenCalled();
  expect(api.submitMessage).not.toHaveBeenCalled();
});

test("项目列表不提供 Entry 正文展开且保持原序编号", async () => {
  const rendered = await renderCard(
    run({
      dialogueBlocks: [
        {
          kind: "list",
          resultType: "projects",
          items: [
            { id: 2, name: "项目乙" },
            { id: 1, name: "项目甲" },
          ],
        },
      ],
    }),
  );
  const tree = JSON.stringify(rendered.toJSON());
  expect(tree.indexOf("项目乙")).toBeLessThan(tree.indexOf("项目甲"));
  expect(rendered.getByLabelText("第 1 项，项目乙")).toBeTruthy();
  expect(rendered.getByLabelText("第 2 项，项目甲")).toBeTruthy();
  expect(api.getEntryCurrent).not.toHaveBeenCalled();
});

test("Evidence、Entry 和未知块使用不同语义且未知块不吞后续内容", async () => {
  const rendered = await renderCard(
    run({
      dialogueBlocks: [
        { kind: "evidence", text: "来源《施工说明》：至少 24 小时", entryId: 8, sourceId: 4 },
        { kind: "future_block", text: "未来内容" },
        { kind: "entry", title: "闭水试验", content: "回答时读取的正文" },
        { kind: "text", text: "后续结论" },
      ],
    }),
  );
  expect(rendered.getByText("本轮已核验依据")).toBeTruthy();
  expect(rendered.getByText("本轮读取的知识正文")).toBeTruthy();
  expect(rendered.getByText("有一项结果暂不支持展示，其余内容不受影响。")).toBeTruthy();
  expect(rendered.getByText("后续结论")).toBeTruthy();
  expect(rendered.queryByText("基于正式知识")).toBeNull();
});

test("无 blocks 时仅做文本回退，可继续入口绑定当前卡", async () => {
  const onContinue = jest.fn();
  const rendered = await renderCard(
    run({ dialogueBlocks: [], canContinue: true, dialogueLoopStatus: "partial_completed" }),
    { onContinue },
  );
  expect(rendered.getByText("扁平答案")).toBeTruthy();
  fireEvent.press(rendered.getByText("继续"));
  expect(onContinue).toHaveBeenCalledTimes(1);
});
