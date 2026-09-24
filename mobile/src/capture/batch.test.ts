import {
  buildCaptureKey,
  createCaptureResults,
  createCaptureSubmitUnits,
  formatImageTitle,
  isBusinessRejection,
  progressText,
  rejectionText,
  successToastText,
  summarizeCapture,
  summaryText,
  type CaptureResult,
  type CaptureSummary,
  type UploadFile,
} from "@/src/capture/batch";

/** 汇总口径的构造器：只写关心的字段，其余取零。 */
function makeSummary(patch: Partial<CaptureSummary>): CaptureSummary {
  return { total: 3, saved: 0, failed: 0, pending: 0, processError: 0, ...patch };
}

const FILES: UploadFile[] = [
  { uri: "file://1.jpg", name: "1.jpg", type: "image/jpeg" },
  { uri: "file://2.jpg", name: "2.jpg", type: "image/jpeg" },
  { uri: "file://3.jpg", name: "3.jpg", type: "image/jpeg" },
];
const NOW = new Date(2026, 8, 23, 15, 20);

test("幂等键按批次与序号派生，序号从 1 开始", () => {
  expect(buildCaptureKey("batch-a", 1)).toBe("batch-a:1");
  expect(buildCaptureKey("batch-a", 3)).toBe("batch-a:3");
  expect(() => buildCaptureKey("batch-a", 0)).toThrow("序号必须从 1 开始");
  expect(() => buildCaptureKey("x".repeat(200), 1)).toThrow("128");
});

test("每张一条派生 N 个单文件单元，重试复用同一键、新一轮换键", () => {
  const first = createCaptureSubmitUnits({
    batchId: "batch-a",
    kind: "album-separate",
    files: FILES,
    now: NOW,
  });
  const retry = createCaptureSubmitUnits({
    batchId: "batch-a",
    kind: "album-separate",
    files: FILES,
    now: NOW,
  });
  const nextRound = createCaptureSubmitUnits({
    batchId: "batch-b",
    kind: "album-separate",
    files: FILES,
    now: NOW,
  });

  expect(first.map((unit) => unit.key)).toEqual(["batch-a:1", "batch-a:2", "batch-a:3"]);
  expect(first.map((unit) => unit.files.length)).toEqual([1, 1, 1]);
  expect(first.map((unit) => unit.title)).toEqual([
    "图片 2026-09-23 15:20 · 1/3",
    "图片 2026-09-23 15:20 · 2/3",
    "图片 2026-09-23 15:20 · 3/3",
  ]);
  expect(retry.map((unit) => unit.key)).toEqual(first.map((unit) => unit.key));
  expect(nextRound.map((unit) => unit.key)).not.toEqual(first.map((unit) => unit.key));
});

test("多张合并一条只派生一个多文件单元", () => {
  const units = createCaptureSubmitUnits({
    batchId: "batch-merged",
    kind: "album-merged",
    files: FILES,
    now: NOW,
  });

  expect(units).toHaveLength(1);
  expect(units[0].key).toBe("batch-merged:1");
  expect(units[0].files).toHaveLength(3);
  expect(units[0].title).toBe("图片 2026-09-23 15:20 · 3 张");
});

test("相机单张标题不带序号", () => {
  expect(formatImageTitle(NOW, { total: 1, merged: false })).toBe("图片 2026-09-23 15:20");
});

test("文本采集派生一个文本单元且不传标题", () => {
  const units = createCaptureSubmitUnits({
    batchId: "batch-text",
    kind: "text",
    text: "  闭水试验 24 小时  ",
  });

  expect(units).toHaveLength(1);
  expect(units[0].key).toBe("batch-text:1");
  expect(units[0].text).toBe("闭水试验 24 小时");
  expect(units[0].title).toBeUndefined();
  expect(units[0].files).toHaveLength(0);
});

test("空内容与超量在派生阶段就被拦下", () => {
  expect(() =>
    createCaptureSubmitUnits({ batchId: "b", kind: "text", text: "   " }),
  ).toThrow("请先输入要收集的文字");
  expect(() =>
    createCaptureSubmitUnits({ batchId: "b", kind: "album-separate", files: [] }),
  ).toThrow("请先选择图片");
  expect(() =>
    createCaptureSubmitUnits({
      batchId: "b",
      kind: "album-separate",
      files: [...FILES, ...FILES, ...FILES].slice(0, 6),
    }),
  ).toThrow("一次最多上传 5 张图片");
});

test("汇总口径区分全部成功与部分失败", () => {
  const units = createCaptureSubmitUnits({
    batchId: "batch-a",
    kind: "album-separate",
    files: FILES,
    now: NOW,
  });
  const results: CaptureResult[] = createCaptureResults(units);
  expect(summarizeCapture(results)).toEqual({
    total: 3,
    saved: 0,
    failed: 0,
    pending: 3,
    processError: 0,
  });

  results[0] = { ...results[0], status: "saved" };
  results[1] = { ...results[1], status: "saved" };
  results[2] = { ...results[2], status: "failed", error: "一次最多上传 5 张图片" };

  const summary = summarizeCapture(results);
  expect(summary).toEqual({ total: 3, saved: 2, failed: 1, pending: 0, processError: 0 });
  expect(summaryText(summary)).toBe("已提交 2 条，1 条未成功");
  expect(summaryText(makeSummary({ saved: 3 }))).toBe("已提交 3 条");
  expect(summaryText(makeSummary({ failed: 3 }))).toBe("已提交 0 条，3 条未成功");
});

test("全部成功后的轻提示在处理未启动时带上数量", () => {
  expect(successToastText(makeSummary({ saved: 3 }))).toBe("已提交 3 条，正在后台处理");
  expect(successToastText(makeSummary({ saved: 3, processError: 1 }))).toBe(
    "已提交 3 条，其中 1 条处理未启动",
  );
});

test("只有「全是 4xx 且无成功条目」才算服务端业务拒绝", () => {
  const rejected: CaptureResult[] = [
    { key: "b:1", status: "failed", error: "仅支持 png、jpg、webp 图片", httpStatus: 400 },
    { key: "b:2", status: "failed", error: "仅支持 png、jpg、webp 图片", httpStatus: 400 },
  ];
  expect(isBusinessRejection(rejected)).toBe(true);
  // 原文去重后按行拼接，不改写文案
  expect(rejectionText(rejected)).toBe("仅支持 png、jpg、webp 图片");

  // 网络类失败没有状态码：留在覆盖层逐条重试
  expect(isBusinessRejection([{ key: "b:1", status: "failed", error: "网络连接中断" }])).toBe(false);
  // 服务端 5xx 也不是业务拒绝
  expect(
    isBusinessRejection([{ key: "b:1", status: "failed", error: "服务暂时不可用", httpStatus: 503 }]),
  ).toBe(false);
  // 有成功条目时按部分失败留在覆盖层，不抹掉已提交的成果
  expect(
    isBusinessRejection([
      { key: "b:1", status: "saved" },
      { key: "b:2", status: "failed", error: "仅支持 png、jpg、webp 图片", httpStatus: 400 },
    ]),
  ).toBe(false);
});

test("进度文案不含百分比", () => {
  expect(progressText("album-separate", { total: 3, current: 2 })).toBe("正在上传 3 张中的第 2 张…");
  expect(progressText("album-separate", { total: 1, current: 1 })).toBe("正在上传 1 张图片…");
  expect(progressText("album-merged", { total: 4, current: 1 })).toBe("正在上传 4 张图片…");
  expect(progressText("text", { total: 1, current: 1 })).toBe("正在提交文字来源…");
});
