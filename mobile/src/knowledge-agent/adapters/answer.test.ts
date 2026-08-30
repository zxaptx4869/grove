import {
  cleanAnswerText,
  draftActionEligibility,
  presentAnswer,
} from "@/src/knowledge-agent/adapters/answer";
import type { KnowledgeAnswer, KnowledgeRun } from "@/src/knowledge-agent/types";

function run(
  overrides: Partial<KnowledgeRun> = {},
): KnowledgeRun {
  return {
    id: 1,
    conversationId: 1,
    runKind: "answer",
    sourceRunId: null,
    status: "completed",
    currentStep: null,
    scopeType: "project",
    projectId: 1,
    projectName: "新房装修",
    userMessageId: 1,
    assistantMessageId: 2,
    cancelRequested: false,
    retryCount: 0,
    maxRetries: 1,
    error: null,
    requestContextMode: null,
    contextDecision: null,
    standaloneQuery: null,
    topicLabel: null,
    requestAnswerMode: null,
    actualAnswerMode: null,
    currentRound: 0,
    inputContextVersionId: null,
    outputContextVersionId: null,
    contextDegraded: false,
    fallbackSummary: null,
    investigationSummary: null,
    answer: null,
    createdAt: "2026-08-29T10:00:00Z",
    updatedAt: "2026-08-29T10:00:00Z",
    ...overrides,
  };
}

function citation(projectId: number, projectName: string) {
  return {
    evidenceId: projectId * 10,
    evidenceHandle: `ev_${projectId}`,
    entryId: projectId,
    entryTitle: "闭水试验",
    sourceId: 1,
    sourceTitle: "验收手册",
    attachmentId: 1,
    quote: "闭水试验通常持续 24 小时",
    scopeType: "project" as const,
    projectId,
    projectName,
    nodePath: "施工",
  };
}

test("cleanAnswerText 移除常见 Markdown 标记但保留换行与内容", () => {
  const text =
    "## 釉面类型对比\n\n**天鹅绒釉面**（易清洁度 4 星）\n- 耐磨\n- 防滑\n1. 先看胚体";
  const cleaned = cleanAnswerText(text);
  expect(cleaned).toContain("釉面类型对比");
  expect(cleaned).toContain("天鹅绒釉面（易清洁度 4 星）");
  expect(cleaned).toContain("耐磨");
  expect(cleaned).toContain("先看胚体");
  expect(cleaned).not.toContain("**");
  expect(cleaned).not.toContain("##");
  expect(cleaned).not.toContain("- 耐磨");
  expect(cleaned).not.toContain("1. ");
});

test("cleanAnswerText 不误删正文中的成对星号", () => {
  expect(cleanAnswerText("规格 100*50 与 80*40 均可")).toBe(
    "规格 100*50 与 80*40 均可",
  );
});

test("后端 insufficient 即使带引用也保持知识不足语义", () => {
  const answer: KnowledgeAnswer = {
    answer: "厨房推荐使用 4000K 色温。",
    status: "insufficient",
    insufficientNote: "调查因证据预算停止，未穷尽全部知识。",
    citations: [
      {
        evidenceId: 1,
        evidenceHandle: "ev_1",
        entryId: 1,
        entryTitle: "厨房灯光",
        sourceId: 1,
        sourceTitle: "来源",
        attachmentId: null,
        quote: "4000K",
        scopeType: "project",
        projectId: 1,
        projectName: "房子装修",
        nodePath: "灯光设计",
      },
    ],
    conflicts: [],
  };
  const presentation = presentAnswer(answer, "completed");
  expect(presentation.status).toBe("insufficient");
  expect(presentation.headline).toBe("知识不足");
  expect(presentation.note).toContain("证据预算");
});

test("insufficient 无引用时仍显示知识不足", () => {
  const answer: KnowledgeAnswer = {
    answer: "",
    status: "insufficient",
    insufficientNote: "没有找到相关证据",
    citations: [],
    conflicts: [],
  };
  const presentation = presentAnswer(answer, "completed");
  expect(presentation.status).toBe("insufficient");
  expect(presentation.headline).toBe("知识不足");
});

test("partial 说明未覆盖内容但不默认宣称发生降级", () => {
  const answer: KnowledgeAnswer = {
    answer: "现有知识确认了清洁频率，但没有覆盖耗材成本。",
    status: "partial",
    insufficientNote: null,
    citations: [],
    conflicts: [],
  };
  const presentation = presentAnswer(answer, "completed");
  expect(presentation.headline).toBe("部分结果");
  expect(presentation.note).toContain("未覆盖或失效内容");
  expect(presentation.note).not.toContain("降级");
});

test("completed 有引用的项目范围回答可整理，目标项目固定", () => {
  const eligibility = draftActionEligibility(
    run({
      scopeType: "project",
      projectId: 3,
      projectName: "新房装修",
      answer: {
        answer: "闭水试验通常持续 24 小时。",
        status: "completed",
        insufficientNote: null,
        citations: [citation(3, "新房装修")],
        conflicts: [],
      },
    }),
  );
  expect(eligibility.eligible).toBe(true);
  expect(eligibility.sourceRunId).toBe(1);
  expect(eligibility.fixedProjectId).toBe(3);
  expect(eligibility.projectOptions).toEqual([{ id: 3, name: "新房装修" }]);
  expect(eligibility.note).toBeNull();
});

test("Workspace 多项目回答返回可选项目且不固定目标", () => {
  const eligibility = draftActionEligibility(
    run({
      scopeType: "workspace",
      projectId: null,
      projectName: null,
      answer: {
        answer: "两条记录都确认了闭水时长。",
        status: "completed",
        insufficientNote: null,
        citations: [citation(1, "项目甲"), citation(2, "项目乙")],
        conflicts: [],
      },
    }),
  );
  expect(eligibility.eligible).toBe(true);
  expect(eligibility.fixedProjectId).toBeNull();
  expect(eligibility.projectOptions.map((item) => item.id)).toEqual([1, 2]);
});

test("partial 有引用可整理并说明只整理有依据部分", () => {
  const eligibility = draftActionEligibility(
    run({
      status: "partial",
      answer: {
        answer: "已有知识确认了闭水时长。",
        status: "partial",
        insufficientNote: null,
        citations: [citation(1, "项目甲")],
        conflicts: [],
      },
    }),
  );
  expect(eligibility.eligible).toBe(true);
  expect(eligibility.note).toContain("只整理有依据部分");
});

test("无引用或不可整理状态不暴露整理入口", () => {
  const withoutCitations = draftActionEligibility(
    run({
      answer: {
        answer: "没有引用。",
        status: "completed",
        insufficientNote: null,
        citations: [],
        conflicts: [],
      },
    }),
  );
  expect(withoutCitations.eligible).toBe(false);
  expect(withoutCitations.sourceRunId).toBeNull();

  const insufficient = draftActionEligibility(
    run({
      answer: {
        answer: "知识不足。",
        status: "insufficient",
        insufficientNote: "无证据",
        citations: [citation(1, "项目甲")],
        conflicts: [],
      },
    }),
  );
  expect(insufficient.eligible).toBe(false);

  const cancelled = draftActionEligibility(
    run({
      status: "cancelled",
      answer: null,
    }),
  );
  expect(cancelled.eligible).toBe(false);
});

test("draft_candidate Run 与旧缺省 runKind 都按只读回答判定", () => {
  const draftRun = draftActionEligibility(
    run({
      runKind: "draft_candidate",
      answer: null,
    }),
  );
  expect(draftRun.eligible).toBe(false);

  const legacyRun = draftActionEligibility(
    run({
      runKind: undefined,
      sourceRunId: undefined,
      answer: {
        answer: "旧回答",
        status: "completed",
        insufficientNote: null,
        citations: [citation(1, "项目甲")],
        conflicts: [],
      },
    }),
  );
  expect(legacyRun.eligible).toBe(true);
});
