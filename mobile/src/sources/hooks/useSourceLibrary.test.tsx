/** useSourceLibrary：列表查询的前台启用与轮询开关条件，以及三个动作的调用口径。 */

import { act, renderHook } from "@testing-library/react-native";

import { useSourceLibrary } from "@/src/sources/hooks/useSourceLibrary";
import { SOURCE_POLL_INTERVAL_MS } from "@/src/sources/state";
import type { SourceOut } from "@/src/sources/types";

let mockAppActive = true;
const mockInvalidateQueries = jest.fn(async () => undefined);
const mockUseQuery = jest.fn((_options: unknown) => stubQuery());
const mockListSources = jest.fn(async (..._args: unknown[]): Promise<unknown> => []);
const mockGetSource = jest.fn(async (..._args: unknown[]): Promise<unknown> => null);
const mockListCandidates = jest.fn(async (..._args: unknown[]): Promise<unknown> => []);
const mockUpdateSourceProject = jest.fn(async (..._args: unknown[]): Promise<unknown> => null);
const mockDeleteSource = jest.fn(async (..._args: unknown[]): Promise<unknown> => ({ ok: true }));
const mockTriggerProcessing = jest.fn(async (..._args: unknown[]): Promise<unknown> => undefined);

jest.mock("@tanstack/react-query", () => ({
  useQuery: (options: unknown) => mockUseQuery(options),
  useQueryClient: () => ({ invalidateQueries: mockInvalidateQueries }),
}));

jest.mock("@/src/knowledge-agent/hooks/useAppState", () => ({
  useAppStateActive: () => mockAppActive,
}));

jest.mock("@/src/sources/api", () => ({
  listSources: (...args: unknown[]) => mockListSources(...(args as [])),
  getSource: (...args: unknown[]) => mockGetSource(...(args as [])),
  listSourceCandidates: (...args: unknown[]) => mockListCandidates(...(args as [])),
  updateSourceProject: (...args: unknown[]) => mockUpdateSourceProject(...(args as [])),
  deleteSource: (...args: unknown[]) => mockDeleteSource(...(args as [])),
  triggerSourceProcessing: (...args: unknown[]) => mockTriggerProcessing(...(args as [])),
  sourceErrorMessage: () => "网络连接中断，请检查网络后重试。",
}));

function stubQuery(data: unknown = undefined) {
  return {
    data,
    error: null,
    isPending: data === undefined,
    isError: false,
    isRefetching: false,
    refetch: jest.fn(async () => ({ data })),
  };
}

function source(overrides: Partial<SourceOut> = {}): SourceOut {
  return {
    id: 1,
    title: "来源",
    note: null,
    project_id: null,
    status: "waiting",
    created_at: "2026-09-24T02:12:00.000Z",
    updated_at: "2026-09-24T02:12:00.000Z",
    attachments: [],
    failure_reason: null,
    retry_count: 0,
    has_processing_task: true,
    project_locked: false,
    evidence_entry_count: 0,
    pending_candidate_count: 0,
    candidate_count: 0,
    ...overrides,
  };
}

type QueryOptions = {
  queryKey: unknown[];
  enabled: boolean;
  refetchInterval: (query: { state: { data?: unknown } }) => number | false;
};

function listOptions(): QueryOptions {
  const call = mockUseQuery.mock.calls.find(
    (item) => (item[0] as QueryOptions).queryKey[1] === "list",
  );
  return call?.[0] as QueryOptions;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockAppActive = true;
  mockUseQuery.mockImplementation(() => stubQuery());
});

test("前台时启用列表查询，并按是否有活动条目决定轮询间隔", async () => {
  await renderHook(() => useSourceLibrary("token"));

  const options = listOptions();
  expect(options.queryKey).toEqual(["sources", "list", "all"]);
  expect(options.enabled).toBe(true);
  expect(options.refetchInterval({ state: { data: [source({ status: "waiting" })] } })).toBe(
    SOURCE_POLL_INTERVAL_MS,
  );
  expect(options.refetchInterval({ state: { data: [source({ status: "processing" })] } })).toBe(
    SOURCE_POLL_INTERVAL_MS,
  );
  expect(options.refetchInterval({ state: { data: [source({ status: "done" })] } })).toBe(false);
  expect(options.refetchInterval({ state: { data: undefined } })).toBe(false);
});

test("进入后台停止请求与轮询", async () => {
  mockAppActive = false;

  await renderHook(() => useSourceLibrary("token"));

  expect(listOptions().enabled).toBe(false);
  expect(listOptions().refetchInterval({ state: { data: [source()] } })).toBe(false);
});

test("重试处理调用处理端点并失效来源缓存", async () => {
  const { result } = await renderHook(() => useSourceLibrary("token"));

  await act(async () => {
    await result.current.retryProcessing(9);
  });

  expect(mockTriggerProcessing).toHaveBeenCalledWith("token", 9);
  expect(mockInvalidateQueries).toHaveBeenCalled();
});

test("改归属请求期间标记正在重新路由，返回后清除", async () => {
  let resolveMove: () => void = () => undefined;
  mockUpdateSourceProject.mockImplementation(
    () => new Promise<void>((resolve) => (resolveMove = resolve)),
  );
  const { result } = await renderHook(() => useSourceLibrary("token"));

  await act(async () => {
    void result.current.moveSource(9, 3);
  });
  expect(result.current.movingIds).toContain(9);

  await act(async () => {
    resolveMove();
  });

  expect(mockUpdateSourceProject).toHaveBeenCalledWith("token", 9, 3);
  expect(result.current.movingIds).not.toContain(9);
});

test("删除成功后关闭详情并失效缓存", async () => {
  const { result } = await renderHook(() => useSourceLibrary("token"));

  await act(async () => {
    result.current.openSource(9);
  });
  expect(result.current.detailSourceId).toBe(9);

  await act(async () => {
    await result.current.removeSource(9);
  });

  expect(mockDeleteSource).toHaveBeenCalledWith("token", 9);
  expect(result.current.detailSourceId).toBeNull();
  expect(mockInvalidateQueries).toHaveBeenCalled();
});
