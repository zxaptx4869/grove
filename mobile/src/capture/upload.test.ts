import type { CaptureSubmitUnit } from "@/src/capture/batch";
import { installExpoFetchFormData } from "@/src/capture/testing/expo-fetch-formdata";
import { CaptureSubmitError, triggerSourceProcessing, uploadSource } from "@/src/capture/upload";

const mockRequest = jest.fn(async (..._args: unknown[]) => ({ id: 1 }));

jest.mock("expo-file-system", () => ({
  // 运行时的 File 是原生类，不是 Blob 实例，只实现 Blob 接口（含 bytes()）
  File: class MockFile {
    uri: string;
    type = "image/jpeg";
    constructor(uri: string) {
      this.uri = uri;
    }
    async bytes() {
      return new Uint8Array();
    }
  },
}));

jest.mock("@/src/api", () => ({
  apiBaseUrl: "http://api.test",
  apiConfigured: true,
  request: (...args: unknown[]) => mockRequest(...args),
}));

const UNIT: CaptureSubmitUnit = {
  key: "batch-a:1",
  title: "图片 2026-09-23 15:20",
  files: [{ uri: "file://a.jpg", name: "a.jpg", type: "image/jpeg" }],
};

const originalFetch = globalThis.fetch;

let restoreFormData: () => void;

beforeEach(() => {
  restoreFormData = installExpoFetchFormData();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  restoreFormData();
  mockRequest.mockReset();
  mockRequest.mockResolvedValue({ id: 1 });
});

function stubFetch(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  const fetchMock = jest.fn(async () => ({
    ok: true,
    status: 201,
    json: async () => ({ id: 7 }),
    ...response,
  }));
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

test("multipart 携带文件与幂等键，且不手动设置 Content-Type", async () => {
  const fetchMock = stubFetch({});

  await uploadSource({ token: "token-1", unit: UNIT, note: "现场记录", projectId: 12 });

  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("http://api.test/api/sources");
  expect(init.method).toBe("POST");
  expect(init.headers).toEqual({ Authorization: "Bearer token-1" });
  const form = init.body as FormData;
  expect(form.get("capture_key")).toBe("batch-a:1");
  expect(form.get("title")).toBe("图片 2026-09-23 15:20");
  expect(form.get("note")).toBe("现场记录");
  expect(form.get("project_id")).toBe("12");
  const parts = form.getAll("files") as unknown as { uri: string; bytes?: unknown }[];
  expect(parts).toHaveLength(1);
  expect(parts[0]?.uri).toBe("file://a.jpg");
  // 必须是带 bytes() 的部件：RN 的 { uri, name, type } 会被 Expo fetch 拒绝
  expect(typeof parts[0]?.bytes).toBe("function");
  expect(form.get("text")).toBeNull();
});

test("文本采集只带 text 且不带 title 与文件", async () => {
  const fetchMock = stubFetch({});
  await uploadSource({
    token: "token-1",
    unit: { key: "batch-t:1", files: [], text: "闭水试验 24 小时" },
  });

  const form = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as FormData;
  expect(form.get("text")).toBe("闭水试验 24 小时");
  expect(form.get("title")).toBeNull();
  expect(form.getAll("files")).toHaveLength(0);
});

test("200 幂等命中与 201 新建都算成功", async () => {
  stubFetch({ status: 200, json: async () => ({ id: 3 }) });
  await expect(uploadSource({ token: "t", unit: UNIT })).resolves.toEqual({ id: 3 });

  stubFetch({ status: 201, json: async () => ({ id: 4 }) });
  await expect(uploadSource({ token: "t", unit: UNIT })).resolves.toEqual({ id: 4 });
});

test("400 原文透传且带状态码", async () => {
  stubFetch({ ok: false, status: 400, json: async () => ({ detail: "单张图片不能超过 10MB" }) });

  await expect(uploadSource({ token: "t", unit: UNIT })).rejects.toMatchObject({
    message: "单张图片不能超过 10MB",
    status: 400,
  });
  expect(new CaptureSubmitError("x", 400).status).toBe(400);
});

test("超时中止上传并提示材料未保存", async () => {
  globalThis.fetch = jest.fn(
    (_url: string, init: RequestInit) =>
      new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => {
          const error = new Error("aborted");
          error.name = "AbortError";
          reject(error);
        });
      }),
  ) as unknown as typeof fetch;

  await expect(uploadSource({ token: "t", unit: UNIT, timeoutMs: 5 })).rejects.toThrow("上传超时");
});

test("网络中断给出可重试文案", async () => {
  globalThis.fetch = jest.fn(async () => {
    throw new TypeError("Network request failed");
  }) as unknown as typeof fetch;

  await expect(uploadSource({ token: "t", unit: UNIT })).rejects.toThrow("网络连接中断");
});

test("逐条触发处理调用 process 端点", async () => {
  await triggerSourceProcessing("token-1", 21);

  expect(mockRequest).toHaveBeenCalledWith("/api/sources/21/process", { method: "POST" }, "token-1");
});

test("处理中或已完成（409）不算失败，不提示处理启动失败", async () => {
  const conflict = Object.assign(new Error("来源正在处理中"), { status: 409 });
  mockRequest.mockRejectedValueOnce(conflict);

  await expect(triggerSourceProcessing("token-1", 21)).resolves.toBeUndefined();
});

test("处理触发真实失败时向上抛出，由界面提示来源已保存", async () => {
  mockRequest.mockRejectedValueOnce(new Error("服务不可用"));

  await expect(triggerSourceProcessing("token-1", 21)).rejects.toThrow("服务不可用");
});
