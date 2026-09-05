import { presentFallback } from "@/src/knowledge-agent/adapters/fallback";
import { presentAnswer } from "@/src/knowledge-agent/adapters/answer";

test("成功阶段不生成虚假降级，补查阶段有专用说明", () => {
  const copy = presentFallback({ hasFallback: true, stages: [
    { purpose: "answer", isFallback: false, provider: "llm", model: "test", error: null },
    { purpose: "coverage_repair_synthesis", isFallback: true,
      provider: "llm", model: "test", error: "结构化输出校验失败" },
  ] });
  expect(copy.lines).toEqual([
    "补查后的回答整理失败，已保留首次回答；补查统计仅为工具结果，尚未完成综合",
  ]);
});

test("知识不足默认说明不推测是否使用模型常识", () => {
  const copy = presentAnswer({ answer: "", status: "insufficient", insufficientNote: null,
                              citations: [], conflicts: [] }, "partial");
  expect(copy.note).not.toContain("没有用模型常识");
  expect(copy.headline).toBe("知识不足");
});
