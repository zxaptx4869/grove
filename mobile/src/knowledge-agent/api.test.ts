import type * as KnowledgeAgentApiModule from "@/src/knowledge-agent/api";

describe("知识 Agent 正式对话 API", () => {
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

  test("创建对话注入 Bearer 并序列化范围", async () => {
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
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer token-1");
    expect(JSON.parse(String(init.body))).toEqual({
      scope_type: "project",
      project_id: 7,
    });
  });

  test("消息提交只携带正式支持的上下文设置", async () => {
    mockFetch({ user_message: {}, run: {} }, 201);
    await api.knowledgeAgentApi.submitMessage("token-2", 9, {
      clientMessageId: "stable-id",
      message: "继续分析",
      contextMode: "continue",
    });
    const [, init] = (globalThis.fetch as jest.Mock).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(JSON.parse(String(init.body))).toEqual({
      client_message_id: "stable-id",
      message: "继续分析",
      context_mode: "continue",
    });
    expect(String(init.body)).not.toMatch(/answer_mode|result_mode|basis_mode|source_run_id/);
  });

  test("递归归一化 dialogue 状态、块及列表字段", async () => {
    mockFetch({
      id: 12,
      conversation_id: 3,
      dialogue_loop_status: "partial_completed",
      dialogue_stage: null,
      dialogue_blocks: [
        {
          kind: "list",
          result_type: "entries",
          items: [{ entry_id: 8, project_name: "项目甲", node_path: "材料/板材" }],
          semantics: { total_count: 1, returned_count: 1, result_role: "authorized" },
        },
      ],
      can_continue: true,
      continuation: { task_type: "finalize_answer" },
    });
    const run = await api.knowledgeAgentApi.getRun("token-3", 12);
    expect(run.dialogueLoopStatus).toBe("partial_completed");
    expect(run.dialogueBlocks[0].resultType).toBe("entries");
    expect(run.dialogueBlocks[0].items?.[0]).toMatchObject({
      entryId: 8,
      projectName: "项目甲",
      nodePath: "材料/板材",
    });
    expect(run.dialogueBlocks[0].semantics).toMatchObject({
      totalCount: 1,
      returnedCount: 1,
      resultRole: "authorized",
    });
    expect(run.canContinue).toBe(true);
  });

  test("消息游标与 Entry 当前正文都使用只读 GET", async () => {
    mockFetch({ items: [], next_cursor: null, runs: [] });
    await api.knowledgeAgentApi.listMessages("token-4", 2, "opaque cursor");
    expect((globalThis.fetch as jest.Mock).mock.calls[0][0]).toContain(
      "/messages?cursor=opaque%20cursor&limit=30",
    );
    expect((globalThis.fetch as jest.Mock).mock.calls[0][1].method).toBeUndefined();

    mockFetch({ id: 18, title: "知识", content: "正文" });
    await api.knowledgeAgentApi.getEntryCurrent("token-4", 18);
    expect((globalThis.fetch as jest.Mock).mock.calls[0][0]).toBe(
      "http://example.test/api/entries/18",
    );
    expect((globalThis.fetch as jest.Mock).mock.calls[0][1].method).toBeUndefined();
  });
});
