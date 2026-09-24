/** 来源库 API：查询串、请求方法与错误文案口径。 */

import {
  deleteSource,
  getSource,
  listSourceCandidates,
  listSources,
  SOURCE_LIST_LIMIT,
  SOURCE_NETWORK_ERROR,
  sourceAttachmentUrl,
  sourceErrorMessage,
  updateSourceProject,
} from "@/src/sources/api";

const mockRequest = jest.fn(async (..._args: unknown[]) => []);

jest.mock("@/src/api", () => ({
  apiBaseUrl: "http://api.test",
  apiConfigured: true,
  request: (...args: unknown[]) => mockRequest(...args),
}));

jest.mock("expo-file-system", () => ({ File: jest.fn() }));

beforeEach(() => {
  mockRequest.mockClear();
  mockRequest.mockResolvedValue([]);
});

test("默认筛选取最近 20 条", async () => {
  await listSources("token", "all");

  expect(SOURCE_LIST_LIMIT).toBe(20);
  expect(mockRequest).toHaveBeenCalledWith("/api/sources?limit=20", {}, "token");
});

test("未归属筛选带上 unassigned", async () => {
  await listSources("token", "unassigned");

  expect(mockRequest).toHaveBeenCalledWith("/api/sources?limit=20&unassigned=true", {}, "token");
});

test("详情与候选按来源读取", async () => {
  await getSource("token", 7);
  await listSourceCandidates("token", 7);

  expect(mockRequest).toHaveBeenNthCalledWith(1, "/api/sources/7", {}, "token");
  expect(mockRequest).toHaveBeenNthCalledWith(2, "/api/sources/7/candidates", {}, "token");
});

test("改归属提交 project_id，未归属提交 null", async () => {
  await updateSourceProject("token", 7, 3);
  await updateSourceProject("token", 7, null);

  expect(mockRequest).toHaveBeenNthCalledWith(
    1,
    "/api/sources/7",
    { method: "PATCH", body: JSON.stringify({ project_id: 3 }) },
    "token",
  );
  expect(mockRequest).toHaveBeenNthCalledWith(
    2,
    "/api/sources/7",
    { method: "PATCH", body: JSON.stringify({ project_id: null }) },
    "token",
  );
});

test("删除使用 DELETE", async () => {
  await deleteSource("token", 7);

  expect(mockRequest).toHaveBeenCalledWith("/api/sources/7", { method: "DELETE" }, "token");
});

test("附件图片地址来自后端附件端点", () => {
  expect(sourceAttachmentUrl(3, 4)).toBe("http://api.test/api/sources/3/attachments/4/file");
});

test("有服务端 detail 的 4xx 原样透传，网络失败用固定文案", () => {
  const conflict = Object.assign(new Error("该来源已被正式知识引用，如需移动请先处理关联 Entry"), {
    status: 409,
  });
  const network = new TypeError("Network request failed");

  expect(sourceErrorMessage(conflict)).toBe("该来源已被正式知识引用，如需移动请先处理关联 Entry");
  expect(sourceErrorMessage(network)).toBe(SOURCE_NETWORK_ERROR);
  expect(sourceErrorMessage(undefined)).toBe(SOURCE_NETWORK_ERROR);
});
