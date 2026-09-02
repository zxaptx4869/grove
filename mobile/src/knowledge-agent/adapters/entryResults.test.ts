import {
  completenessCopy,
  firstPageItems,
  resultStatusCopy,
  snapshotHasMore,
} from "@/src/knowledge-agent/adapters/entryResults";
import type { KnowledgeEntryResultSnapshot } from "@/src/knowledge-agent/types";

function snapshot(
  overrides: Partial<KnowledgeEntryResultSnapshot> = {},
): KnowledgeEntryResultSnapshot {
  return {
    schemaVersion: "v1",
    query: "经验",
    status: "completed",
    completeness: "complete",
    items: [],
    returnedCount: 0,
    candidateLimit: 50,
    warning: null,
    snapshotUpdatedAt: "2026-09-02T00:00:00Z",
    ...overrides,
  };
}

describe("Entry 结果协议适配", () => {
  test("旧 v1 和缺少 v2 字段时保持既有分页与完整性语义", () => {
    const legacy = snapshot();
    expect(legacy.setSummary).toBeUndefined();
    expect(firstPageItems(legacy)).toEqual([]);
    expect(snapshotHasMore(legacy)).toBe(false);
    expect(completenessCopy(legacy.completeness)).toBe(
      "已完整列出当前范围匹配的正式知识",
    );
  });

  test("v2 聚合与分输出完整性不从 Entry 数量推断", () => {
    const structured = snapshot({
      schemaVersion: "v2",
      completeness: "limited",
      count: { value: 23, completeness: "complete", status: "completed" },
      groupCounts: [
        {
          groupBy: "info_nature",
          buckets: [{ key: "unspecified", count: 4 }],
          completeness: "complete",
          status: "completed",
          truncated: false,
        },
      ],
      outputCompleteness: {
        entries: "limited",
        count: "complete",
        groupCount: { infoNature: "complete" },
      },
    });
    expect(structured.items).toHaveLength(0);
    expect(structured.count?.value).toBe(23);
    expect(structured.outputCompleteness?.entries).toBe("limited");
    expect(structured.outputCompleteness?.groupCount.infoNature).toBe("complete");
    expect(completenessCopy(structured.completeness)).toContain("可能不完整");
  });

  test("partial 只表达服务端快照状态", () => {
    expect(resultStatusCopy(snapshot({ status: "partial" }))).toContain(
      "部分匹配对象当前不可用",
    );
  });
});
