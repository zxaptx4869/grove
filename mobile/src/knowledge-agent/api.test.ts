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
      resultMode: "entries",
      basisMode: "auto",
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
      result_mode: "entries",
      basis_mode: "auto",
    });
  });

  test("模式纠正提交来源 Run，由服务端恢复原问题上下文", async () => {
    mockFetch({ user_message: {}, run: {} }, 201);
    await api.knowledgeAgentApi.submitMessage("token-2", 9, {
      clientMessageId: "resubmit-id",
      message: "展示用问题",
      contextMode: "auto",
      answerMode: "auto",
      resultMode: "answer",
      basisMode: "auto",
      sourceRunId: 17,
    });
    const [, init] = (globalThis.fetch as jest.Mock).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(JSON.parse(String(init.body))).toEqual({
      client_message_id: "resubmit-id",
      message: "展示用问题",
      context_mode: "auto",
      answer_mode: "auto",
      result_mode: "answer",
      basis_mode: "auto",
      source_run_id: 17,
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

  test("Run 与结果分页递归适配 v2 结构化查询字段", async () => {
    const structured = {
      schema_version: "v2",
      status: "completed",
      completeness: "limited",
      items: [],
      returned_count: 0,
      total_in_snapshot: 0,
      candidate_limit: 6,
      has_more: false,
      next_cursor: null,
      warning: null,
      snapshot_updated_at: "2026-09-02T00:00:00Z",
      set_summary: {
        schema_version: "v1",
        scope_type: "workspace",
        project_id: null,
        project_name: null,
        semantic_query: "防水",
        main_types: ["knowledge"],
        info_natures: ["fact"],
        updated_at_from: null,
        updated_at_to: null,
        completeness: "limited",
      },
      sort: {
        field: "relevance",
        direction: "desc",
        tie_breaker: "entry_id",
      },
      count: { value: 3, completeness: "limited", status: "limited" },
      group_counts: [
        {
          group_by: "info_nature",
          buckets: [{ key: "unspecified", count: 1 }],
          completeness: "limited",
          status: "limited",
          truncated: false,
        },
      ],
      output_completeness: {
        entries: "limited",
        count: "limited",
        group_count: { info_nature: "limited" },
      },
      warnings: ["语义查询只覆盖本次候选集合"],
    };
    mockFetch(structured);
    const page = await api.knowledgeAgentApi.getEntryResults("token-v2", 8, null, 6);
    expect(page.setSummary?.semanticQuery).toBe("防水");
    expect(page.sort?.tieBreaker).toBe("entry_id");
    expect(page.groupCounts?.[0].groupBy).toBe("info_nature");
    expect(page.outputCompleteness?.groupCount.infoNature).toBe("limited");

    mockFetch({
      id: 8,
      structured_query_plan: {
        schema_version: "v1",
        prompt_version: "v1",
        entry_set: {
          schema_version: "v1",
          semantic_query: null,
          main_types: ["knowledge"],
          info_natures: [],
          updated_at: null,
        },
        outputs: [{ kind: "group_count", group_by: "main_type" }],
      },
    });
    const run = await api.knowledgeAgentApi.getRun("token-v2", 8);
    expect(run.structuredQueryPlan?.entrySet.mainTypes).toEqual(["knowledge"]);
    expect(run.structuredQueryPlan?.outputs[0]).toMatchObject({
      kind: "group_count",
      groupBy: "main_type",
    });
  });

  test("提交修订动作序列化 source/target/instruction 并携带 client_message_id", async () => {
    mockFetch({ user_message: {}, run: {}, draft: {} }, 201);
    await api.knowledgeAgentApi.submitEntryRevision("token-r", 9, {
      clientMessageId: "rev-1",
      sourceRunId: 5,
      targetEntryId: 3,
      instruction: "补充适用条件",
    });
    const [url, init] = (globalThis.fetch as jest.Mock).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe(
      "http://example.test/api/knowledge-agent/conversations/9/entry-revision-drafts",
    );
    expect(JSON.parse(String(init.body))).toEqual({
      client_message_id: "rev-1",
      source_run_id: 5,
      target_entry_id: 3,
      instruction: "补充适用条件",
    });
  });

  test("编辑修订草稿序列化候选字段", async () => {
    mockFetch({ id: 7 });
    await api.knowledgeAgentApi.editEntryRevisionDraft("token-r", 7, {
      title: "新标题",
      content: "新内容",
      applicableCondition: "南方潮湿地区",
      changeSummary: "改写",
    });
    const [, init] = (globalThis.fetch as jest.Mock).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(JSON.parse(String(init.body))).toEqual({
      title: "新标题",
      content: "新内容",
      main_type: null,
      info_nature: null,
      applicable_condition: "南方潮湿地区",
      note: null,
      change_summary: "改写",
    });
  });

  test("确认与撤销修订序列化 client_operation_id", async () => {
    mockFetch({ draft: {}, execution: {}, entry: {} });
    await api.knowledgeAgentApi.confirmEntryRevision("token-r", 7, {
      clientOperationId: "confirm-1",
    });
    const [confirmUrl, confirmInit] = (globalThis.fetch as jest.Mock).mock
      .calls[0] as [string, RequestInit];
    expect(confirmUrl).toBe(
      "http://example.test/api/knowledge-agent/entry-revision-drafts/7/confirm",
    );
    expect(JSON.parse(String(confirmInit.body))).toEqual({
      client_operation_id: "confirm-1",
    });

    await api.knowledgeAgentApi.undoEntryRevision("token-r", 7, {
      clientOperationId: "undo-1",
    });
    const [undoUrl, undoInit] = (globalThis.fetch as jest.Mock).mock
      .calls[1] as [string, RequestInit];
    expect(undoUrl).toBe(
      "http://example.test/api/knowledge-agent/entry-revision-drafts/7/undo",
    );
    expect(JSON.parse(String(undoInit.body))).toEqual({
      client_operation_id: "undo-1",
    });
  });

  test("读取当前正式知识使用 Bearer 与 entry 路径", async () => {
    mockFetch({ id: 3, title: "闭水试验", content: "内容", updated_at: "2026-08-29T10:00:00Z" });
    const result = await api.knowledgeAgentApi.getEntryCurrent("token-r", 3);
    const [url, init] = (globalThis.fetch as jest.Mock).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe("http://example.test/api/entries/3");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer token-r",
    );
    expect(result).toMatchObject({
      id: 3,
      title: "闭水试验",
      content: "内容",
      updatedAt: "2026-08-29T10:00:00Z",
    });
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
        resultMode: "auto",
        basisMode: "knowledge_only",
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
