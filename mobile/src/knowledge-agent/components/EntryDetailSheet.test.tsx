import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import { EntryDetailSheet } from "@/src/knowledge-agent/components/EntryDetailSheet";

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ token: "token", me: null }),
}));

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

afterEach(async () => {
  cleanup();
  await act(async () => {
    await Promise.all(clients.map((client) => client.cancelQueries()));
  });
  clients.forEach((client) => client.clear());
  clients.length = 0;
  jest.clearAllMocks();
});

test("底部详情首次打开只读取单个 Entry，关闭不触发消息或模型", async () => {
  api.getEntryCurrent.mockResolvedValue({
    id: 8,
    projectId: 1,
    nodeId: 2,
    nodeName: "防水",
    title: "闭水试验",
    content: "当前正文采用正常阅读字号。",
    mainType: "knowledge",
    infoNature: null,
    applicableCondition: null,
    note: null,
    createdAt: "2026-09-01T00:00:00Z",
    updatedAt: "2026-09-19T00:00:00Z",
    evidences: [
      { id: 3, sourceId: 4, sourceTitle: "施工说明", quote: "至少 24 小时" },
    ],
  });
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
  fireEvent.press(rendered.getByLabelText("关闭"));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(api.submitMessage).not.toHaveBeenCalled();
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

  api.getEntryCurrent.mockRejectedValueOnce(Object.assign(new Error("不存在"), { status: 404 }));
  await act(async () => {
    fireEvent.press(rendered.getByText("重试读取"));
  });
  await waitFor(() => expect(rendered.getByText("该知识当前不可访问")).toBeTruthy());
  expect(rendered.queryByText("重试读取")).toBeNull();
});
