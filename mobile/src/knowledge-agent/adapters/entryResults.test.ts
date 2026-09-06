import {
  completenessCopy,
  firstPageItems,
  resultStatusCopy,
  snapshotHasMore,
  groupBucketLabel,
  groupLabel,
  structuredFilterCopies,
} from "@/src/knowledge-agent/adapters/entryResults";
import type { KnowledgeEntryResultSnapshot, KnowledgeGroupCountResult } from "@/src/knowledge-agent/types";

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


test("项目桶显示服务端名称并保留零条项目与旧桶兼容", () => {
  const group: KnowledgeGroupCountResult = {
    groupBy: "project",
    buckets: [{ key: "26", label: "房子装修", count: 92 }, { key: "27", label: "旅行", count: 0 }],
    completeness: "complete", status: "completed", truncated: false,
  };
  expect(groupLabel(group)).toBe("按项目");
  expect(groupBucketLabel(group, "27")).toBe("旅行");
  expect(groupBucketLabel({ ...group, buckets: [{ key: "26", count: 1 }] }, "26")).toBe("26");
  expect(structuredFilterCopies({
    schemaVersion: "v1", scopeType: "project", projectId: 26, projectName: "房子装修",
    semanticQuery: null, mainTypes: [], infoNatures: [], updatedAtFrom: null, updatedAtTo: null,
    completeness: "complete",
  })).toEqual(["项目：房子装修"]);
});
