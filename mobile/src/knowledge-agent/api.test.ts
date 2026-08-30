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
    mockFetch({
      items: [
        {
          id: 1,
          conversation_id: 4,
          role: "user",
          message_type: "user",
          content: "问题",
          client_message_id: "c-1",
          run_id: 9,
          scope_type: "project",
          project_id: 7,
          project_name: "项目",
          request_context_mode: "auto",
          context_decision: "new_topic",
          standalone_query: "问题",
          topic_label: "主题",
          request_answer_mode: "auto",
          actual_answer_mode: "quick",
          current_round: 0,
          input_context_version_id: null,
          output_context_version_id: null,
          created_at: "2026-08-29T10:00:00Z",
        },
      ],
      next_cursor: "cursor-next",
      runs: [
        {
          id: 9,
          conversation_id: 4,
          status: "completed",
          scope_type: "project",
          project_id: 7,
          project_name: "项目",
          answer: {
            answer: "正文",
            status: "completed",
            insufficient_note: null,
            citations: [],
            conflicts: [],
          },
        },
      ],
    });
    const page = await api.knowledgeAgentApi.listMessages(
      "token-3",
      4,
      "before-cursor",
    );
    const [url] = (globalThis.fetch as jest.Mock).mock.calls[0] as [string];
    expect(url).toContain(
      "/conversations/4/messages?cursor=before-cursor&limit=30",
    );
    // snake_case → camelCase 归一化
    expect(page.items[0].conversationId).toBe(4);
    expect(page.items[0].runId).toBe(9);
    expect(page.items[0].scopeType).toBe("project");
    expect(page.nextCursor).toBe("cursor-next");
    expect(page.runs[0].projectName).toBe("项目");
    expect(page.runs[0].answer?.insufficientNote).toBeNull();
  });

  test("整理动作序列化 source_run_id 与目标项目", async () => {
    mockFetch(
      {
        user_message: {
          id: 1,
          conversation_id: 9,
          role: "user",
          message_type: "user",
          content: "整理成知识",
          client_message_id: "action-1",
          run_id: 10,
          scope_type: "project",
          project_id: 7,
          project_name: "项目",
          created_at: "2026-08-29T10:00:00Z",
        },
        run: {
          id: 10,
          conversation_id: 9,
          run_kind: "draft_candidate",
          source_run_id: 5,
          status: "waiting",
          scope_type: "project",
          project_id: 7,
          project_name: "项目",
          created_at: "2026-08-29T10:00:00Z",
          updated_at: "2026-08-29T10:00:00Z",
        },
        draft: {
          id: 3,
          conversation_id: 9,
          operation_run_id: 10,
          source_run_id: 5,
          target_project_id: 7,
          target_project_name: "项目",
          status: "generating",
          evidence_handles: [],
          evidence_summaries: [],
          generation_degraded: false,
          created_at: "2026-08-29T10:00:00Z",
          updated_at: "2026-08-29T10:00:00Z",
        },
      },
      201,
    );
    const result = await api.knowledgeAgentApi.submitDraftAction(
      "token-5",
      9,
      { clientMessageId: "action-1", sourceRunId: 5, targetProjectId: 7 },
    );
    const [url, init] = (globalThis.fetch as jest.Mock).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe(
      "http://example.test/api/knowledge-agent/conversations/9/drafts",
    );
    expect(JSON.parse(String(init.body))).toEqual({
      client_message_id: "action-1",
      source_run_id: 5,
      target_project_id: 7,
    });
    expect(result.run.runKind).toBe("draft_candidate");
    expect(result.run.sourceRunId).toBe(5);
    expect(result.draft.targetProjectName).toBe("项目");
    expect(result.draft.status).toBe("generating");
  });

  test("确认请求只序列化 client_operation_id，回执归一化", async () => {
    mockFetch({
      draft: {
        id: 3,
        conversation_id: 9,
        operation_run_id: 10,
        source_run_id: 5,
        target_project_id: 7,
        target_project_name: "项目",
        status: "confirmed",
        title: "闭水试验要点",
        content: "闭水试验通常持续 24 小时。",
        main_type: "knowledge",
        evidence_handles: ["ev_1"],
        evidence_summaries: [],
        generation_degraded: false,
        confirmed_candidate_id: 99,
        created_at: "2026-08-29T10:00:00Z",
        updated_at: "2026-08-29T10:00:00Z",
      },
      candidate: {
        id: 99,
        title: "闭水试验要点",
        status: "pending",
        source_id: 12,
        routing_status: "pending",
        relation_status: "pending",
        created_at: "2026-08-29T10:00:00Z",
      },
    });
    const result = await api.knowledgeAgentApi.confirmDraft("token-6", 3, {
      clientOperationId: "op-1",
    });
    const [url, init] = (globalThis.fetch as jest.Mock).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe(
      "http://example.test/api/knowledge-agent/drafts/3/confirm",
    );
    expect(JSON.parse(String(init.body))).toEqual({
      client_operation_id: "op-1",
    });
    expect(result.draft.status).toBe("confirmed");
    expect(result.draft.confirmedCandidateId).toBe(99);
    expect(result.candidate.status).toBe("pending");
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
