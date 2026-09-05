/** 降级摘要 → 面向用户的短说明；不默认暴露 provider/model/堆栈。 */

import type { FallbackSummary } from "@/src/knowledge-agent/types";

export interface FallbackCopy {
  hasFallback: boolean;
  lines: string[];
}

const PURPOSE_COPY: Record<string, string> = {
  result_mode_route: "结果形式判断降级，已按综合回答处理",
  answer_mode_route: "回答方式路由不可用，已改用快速回答",
  context_decision: "上下文判断降级，已按新话题处理",
  synthesis: "综合回答阶段降级，结果可能不完整",
  answer: "回答生成阶段降级，结果可能不完整",
  embedding: "语义检索降级，可能影响命中范围",
  rerank: "结果排序降级，可能影响相关度",
  investigation_controller: "调查规划降级，已提前停止补查",
  coverage_repair_plan: "补查规划失败，已保留首次回答，未解决的缺口仍然存在",
  coverage_repair_graph: "补查执行失败，已保留可用结果，补查未完整完成",
  coverage_repair_synthesis: "补查后的回答整理失败，已保留首次回答；补查统计仅为工具结果，尚未完成综合",
};

export function presentFallback(
  summary: FallbackSummary | null | undefined,
): FallbackCopy {
  if (!summary || !summary.hasFallback || summary.stages.length === 0) {
    return { hasFallback: false, lines: [] };
  }
  const lines = summary.stages.filter((stage) => stage.isFallback).map((stage) => {
    if (stage.purpose) {
      return PURPOSE_COPY[stage.purpose] ?? "部分步骤降级，结果可能不完整";
    }
    return "部分步骤降级，结果可能不完整";
  });
  return {
    hasFallback: true,
    lines: Array.from(new Set(lines.length ? lines : ["部分步骤降级，结果可能不完整"])),
  };
}
