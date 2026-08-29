import {
  cleanAnswerText,
  presentAnswer,
} from "@/src/knowledge-agent/adapters/answer";
import type { KnowledgeAnswer } from "@/src/knowledge-agent/types";

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

test("insufficient 但有引用与实质内容时按部分结果展示", () => {
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
  expect(presentation.status).toBe("partial");
  expect(presentation.headline).toBe("部分结果");
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
