import {
  createCaptureResults,
  createCaptureSubmitUnits,
  type CaptureResult,
  type UploadFile,
} from "@/src/capture/batch";
import { submitCaptureUnits, toCaptureMessage, type CaptureSubmitDeps } from "@/src/capture/submit";

const FILES: UploadFile[] = [
  { uri: "file://1.jpg", name: "1.jpg", type: "image/jpeg" },
  { uri: "file://2.jpg", name: "2.jpg", type: "image/jpeg" },
  { uri: "file://3.jpg", name: "3.jpg", type: "image/jpeg" },
];

function units() {
  return createCaptureSubmitUnits({ batchId: "batch-a", kind: "album-separate", files: FILES });
}

function harness(overrides: Partial<CaptureSubmitDeps> = {}) {
  const results: CaptureResult[] = createCaptureResults(units());
  const order: string[] = [];
  const deps: CaptureSubmitDeps = {
    upload: async (unit) => {
      order.push(`upload:${unit.key}`);
      return Number(unit.key.split(":")[1]);
    },
    triggerProcessing: async (sourceId) => {
      order.push(`process:${sourceId}`);
    },
    onUpdate: (key, patch) => {
      const index = results.findIndex((item) => item.key === key);
      results[index] = { ...results[index], ...patch };
    },
    ...overrides,
  };
  return { deps, results, order };
}

test("串行提交并在每条成功后立即触发处理", async () => {
  const { deps, results, order } = harness();

  await submitCaptureUnits(units(), deps);

  expect(order).toEqual(["upload:batch-a:1", "process:1", "upload:batch-a:2", "process:2", "upload:batch-a:3", "process:3"]);
  expect(results.map((item) => item.status)).toEqual(["saved", "saved", "saved"]);
  expect(results.map((item) => item.sourceId)).toEqual([1, 2, 3]);
});

test("部分失败继续提交其余条目并保留失败原因", async () => {
  const { deps, results } = harness({
    upload: async (unit) => {
      if (unit.key === "batch-a:2") throw new Error("仅支持 png、jpg、webp 图片");
      return Number(unit.key.split(":")[1]);
    },
  });

  await submitCaptureUnits(units(), deps);

  expect(results.map((item) => item.status)).toEqual(["saved", "failed", "saved"]);
  expect(results[1].error).toBe("仅支持 png、jpg、webp 图片");
  expect(results[1].sourceId).toBeUndefined();
});

test("处理启动失败时条目仍是已保存并单独提示", async () => {
  const { deps, results } = harness({
    triggerProcessing: async (sourceId) => {
      if (sourceId === 2) throw new Error("来源正在处理中");
    },
  });

  await submitCaptureUnits(units(), deps);

  expect(results.map((item) => item.status)).toEqual(["saved", "saved", "saved"]);
  expect(results[1].processError).toBe("来源正在处理中");
  expect(results[1].sourceId).toBe(2);
});

test("只重试失败项时沿用同一个幂等键", async () => {
  const all = units();
  let failedOnce = false;
  const { deps, results } = harness({
    upload: async (unit) => {
      if (unit.key === "batch-a:2" && !failedOnce) {
        failedOnce = true;
        throw new Error("网络连接中断");
      }
      return Number(unit.key.split(":")[1]);
    },
  });

  await submitCaptureUnits(all, deps);
  expect(results[1].status).toBe("failed");

  const retried: string[] = [];
  await submitCaptureUnits(
    all.filter((unit) => unit.key === "batch-a:2"),
    {
      ...deps,
      upload: async (unit) => {
        retried.push(unit.key);
        return 2;
      },
    },
  );

  expect(retried).toEqual(["batch-a:2"]);
  expect(results.map((item) => item.status)).toEqual(["saved", "saved", "saved"]);
});

test("未知错误回落到可读文案", () => {
  expect(toCaptureMessage(new Error("服务端原文"))).toBe("服务端原文");
  expect(toCaptureMessage(undefined)).toBe("提交未成功，请稍后重试。");
});
