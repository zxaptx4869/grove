import type * as KnowledgeAgentApiModule from "@/src/knowledge-agent/api";

describe("知识 Agent API 序列化", () => {
  let api: typeof KnowledgeAgentApiModule;
  const originalFetch = globalThis.fetch;

  beforeAll(() => {
    process.env.EXPO_PUBLIC_API_BASE_URL = "http://example.test/";
    jest.resetModules();
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    api = require("@/src/knowledge-agent/api");
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function mockFetch(response: unknown, status = 200) {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => response,
    }) as unknown as typeof fetch;
  }

  test("创建对话序列化 scope_type/project_id 并注入 Bearer", async () => {
    mockFetch({ id: 1, scope_type: "project" });
    await api.knowledgeAgentApi.createConversation("token-1", {
      scopeType: "project",
      projectId: 7,
    });
    const [url, init] = (globalThis.fetch as jest.Mock).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe("http://example.test/api/knowledge-agent/conversations");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer token-1",
    );
    expect(JSON.parse(String(init.body))).toEqual({
      scope_type: "project",
      project_id: 7,
    });
  });

  test("提交消息携带稳定 client_message_id 与模式参数", async () => {
    mockFetch({ user_message: {}, run: {} }, 201);
    await api.knowledgeAgentApi.submitMessage("token-2", 9, {
      clientMessageId: "stable-id",
      message: "闭水试验多久？",
      contextMode: "continue",
      answerMode: "investigate",
    });
    const [url, init] = (globalThis.fetch as jest.Mock).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe(
      "http://example.test/api/knowledge-agent/conversations/9/messages",
    );
    expect(JSON.parse(String(init.body))).toEqual({
      client_message_id: "stable-id",
      message: "闭水试验多久？",
      context_mode: "continue",
      answer_mode: "investigate",
    });
  });

  test("消息分页使用不透明 before 游标", async () => {
    mockFetch({ items: [], next_cursor: null, runs: [] });
    await api.knowledgeAgentApi.listMessages("token-3", 4, "before-cursor");
    const [url] = (globalThis.fetch as jest.Mock).mock.calls[0] as [string];
    expect(url).toContain(
      "/conversations/4/messages?cursor=before-cursor&limit=30",
    );
  });

  test("409 冲突与网络错误转换为可识别结果", async () => {
    mockFetch({ detail: "存在进行中的问答" }, 409);
    await expect(
      api.knowledgeAgentApi.submitMessage("token-4", 1, {
        clientMessageId: "x",
        message: "问题",
        contextMode: "auto",
        answerMode: "auto",
      }),
    ).rejects.toMatchObject({ kind: "conflict", status: 409 });

    (globalThis.fetch as jest.Mock).mockRejectedValueOnce(
      new TypeError("Network request failed"),
    );
    await expect(
      api.knowledgeAgentApi.getRun("token-4", 2),
    ).rejects.toMatchObject({ kind: "network", retryable: true });
  });
});
