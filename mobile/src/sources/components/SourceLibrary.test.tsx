/**
 * 收集栏目入口页的来源库集成：列表四态、筛选、失败重试、只读详情、改归属与删除。
 * 全部通过 mock 的接口数据驱动，不依赖真机或模拟器。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { CaptureScreen } from "@/src/capture/components/CaptureScreen";
import type { SourceOut } from "@/src/sources/types";

const mockListSources = jest.fn(async (..._args: unknown[]): Promise<unknown> => []);
const mockGetSource = jest.fn(async (..._args: unknown[]): Promise<unknown> => null);
const mockListCandidates = jest.fn(async (..._args: unknown[]): Promise<unknown> => []);
const mockUpdateSourceProject = jest.fn(async (..._args: unknown[]): Promise<unknown> => null);
const mockDeleteSource = jest.fn(async (..._args: unknown[]): Promise<unknown> => ({ ok: true }));
const mockTriggerProcessing = jest.fn(async (..._args: unknown[]): Promise<unknown> => undefined);
const mockGetProjects = jest.fn(async (..._args: unknown[]): Promise<unknown> => []);

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ token: "token", me: null }),
}));

jest.mock("@/src/api", () => ({
  apiBaseUrl: "http://api.test",
  apiConfigured: true,
  getProjects: () => mockGetProjects(),
  request: jest.fn(),
}));

jest.mock("@/src/sources/api", () => {
  const actual = jest.requireActual("@/src/sources/api");
  return {
    ...actual,
    listSources: (...args: unknown[]) => mockListSources(...args),
    getSource: (...args: unknown[]) => mockGetSource(...args),
    listSourceCandidates: (...args: unknown[]) => mockListCandidates(...args),
    updateSourceProject: (...args: unknown[]) => mockUpdateSourceProject(...args),
    deleteSource: (...args: unknown[]) => mockDeleteSource(...args),
    triggerSourceProcessing: (...args: unknown[]) => mockTriggerProcessing(...args),
  };
});

jest.mock("@/src/knowledge-agent/hooks/useAppState", () => ({
  useAppStateActive: () => true,
}));

jest.mock("expo-crypto", () => ({ randomUUID: () => "batch-uuid" }));
jest.mock("expo-clipboard", () => ({ getStringAsync: jest.fn(async () => "") }));
jest.mock("expo-file-system", () => ({
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
jest.mock("expo-image-picker", () => ({
  getCameraPermissionsAsync: jest.fn(),
  requestCameraPermissionsAsync: jest.fn(),
  getMediaLibraryPermissionsAsync: jest.fn(),
  requestMediaLibraryPermissionsAsync: jest.fn(),
  launchCameraAsync: jest.fn(),
  launchImageLibraryAsync: jest.fn(),
}));
jest.mock("expo-image-manipulator", () => ({
  SaveFormat: { JPEG: "jpeg" },
  ImageManipulator: { manipulate: jest.fn() },
}));

function source(overrides: Partial<SourceOut> = {}): SourceOut {
  return {
    id: 1,
    title: "厨房插座位置确认",
    note: null,
    project_id: null,
    status: "waiting",
    created_at: "2026-09-24T02:12:00.000Z",
    updated_at: "2026-09-24T02:12:00.000Z",
    attachments: [
      {
        id: 11,
        kind: "image",
        position: 0,
        mime_type: "image/jpeg",
        file_name: "a.jpg",
        text_content: null,
        ocr_text: null,
      },
    ],
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

/** 等异步失效与重取跑完：waitFor 不会继续推进已经排队的失效链，需要显式让出控制权。 */
async function flushAsyncWork(ms = 300) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

function conflictError(message: string) {
  return Object.assign(new Error(message), { status: 409 });
}

async function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 47, left: 0, right: 0, bottom: 34 },
      }}
    >
      <QueryClientProvider client={client}>
        <CaptureScreen />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

function buttonLabels(screen: { getAllByRole: (role: string) => { props: { accessibilityLabel?: string } }[] }) {
  return screen
    .getAllByRole("button")
    .map((node) => node.props.accessibilityLabel)
    .filter((label): label is string => Boolean(label));
}

beforeEach(() => {
  // 必须 reset：mockResolvedValue / mockRejectedValue 的实现不会被 clearAllMocks 清掉，
  // 上个用例的 409 拒绝会污染下一个用例
  jest.resetAllMocks();
  mockListSources.mockResolvedValue([]);
  mockGetSource.mockResolvedValue(source());
  mockListCandidates.mockResolvedValue([]);
  mockUpdateSourceProject.mockResolvedValue(null);
  mockDeleteSource.mockResolvedValue({ ok: true });
  mockTriggerProcessing.mockResolvedValue(undefined);
  mockGetProjects.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
});

test("列表显示类型、附件与时间、状态徽标、副状态与失败原因，且不显示补充说明", async () => {
  mockListSources.mockResolvedValue([
    source({
      id: 1,
      title: "厨房插座位置确认",
      note: "这是只在详情里出现的补充说明",
      status: "done",
      pending_candidate_count: 2,
      evidence_entry_count: 0,
    }),
    source({ id: 2, title: "闭水试验记录", project_id: 5, status: "waiting", has_processing_task: true }),
    source({
      id: 3,
      title: "瓷砖铺贴顺序",
      status: "failed",
      failure_reason: "模型调用失败，请稍后重试",
    }),
  ]);
  mockGetProjects.mockResolvedValue([{ id: 5, name: "新房装修", description: null, status: "active" }]);

  const screen = await renderScreen();

  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  expect(screen.getByText("等待处理")).toBeTruthy();
  expect(screen.getByText("提取完成")).toBeTruthy();
  expect(screen.getByText("处理失败")).toBeTruthy();
  expect(screen.getByText("待确认 2 条")).toBeTruthy();
  expect(screen.getByText("新房装修")).toBeTruthy();
  expect(screen.getAllByText("未归属").length).toBeGreaterThan(1);
  expect(screen.getByText("模型调用失败，请稍后重试")).toBeTruthy();
  expect(screen.queryByText("这是只在详情里出现的补充说明")).toBeNull();
});

test("列表为空时给出说明与一个采集动作", async () => {
  const screen = await renderScreen();

  await waitFor(() => expect(screen.getByText("还没有来源")).toBeTruthy());
  expect(screen.getByLabelText("从相册采集")).toBeTruthy();
});

test("列表加载失败时可重新加载", async () => {
  mockListSources.mockRejectedValueOnce(new TypeError("Network request failed"));
  const screen = await renderScreen();

  await waitFor(() => expect(screen.getByText("来源列表加载失败")).toBeTruthy());
  expect(screen.getByText("网络连接中断，请检查网络后重试。")).toBeTruthy();

  fireEvent.press(screen.getByLabelText("重新加载"));
  await waitFor(() => expect(mockListSources).toHaveBeenCalledTimes(2));
});

test("筛选在两态间切换并重新查询", async () => {
  const screen = await renderScreen();

  await waitFor(() => expect(mockListSources).toHaveBeenCalledWith("token", "all"));
  fireEvent.press(screen.getByLabelText("未归属"));

  await waitFor(() => expect(mockListSources).toHaveBeenCalledWith("token", "unassigned"));
});

test("等待处理但没有任务时显示处理未启动，重试处理调用处理端点", async () => {
  mockListSources.mockResolvedValue([
    source({ id: 7, title: "没有任务的来源", status: "waiting", has_processing_task: false }),
  ]);
  const screen = await renderScreen();

  await waitFor(() => expect(screen.getByText("处理未启动")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("重试处理：没有任务的来源"));

  await waitFor(() => expect(mockTriggerProcessing).toHaveBeenCalledWith("token", 7));
});

test("详情只读：展示元信息、原始材料、OCR 与候选，且没有任何候选写入入口", async () => {
  const detail = source({
    id: 1,
    title: "厨房插座位置确认",
    note: "水电定位时拍的",
    status: "done",
    pending_candidate_count: 1,
    candidate_count: 1,
    attachments: [
      {
        id: 11,
        kind: "image",
        position: 0,
        mime_type: "image/jpeg",
        file_name: "a.jpg",
        text_content: null,
        ocr_text: "识别到的现场文字",
      },
    ],
  });
  mockListSources.mockResolvedValue([source({ id: 1, status: "done" })]);
  mockGetSource.mockResolvedValue(detail);
  mockListCandidates.mockResolvedValue([
    {
      id: 21,
      candidate_kind: "entry",
      title: "插座高度",
      content: "插座底边离地 30 厘米",
      main_type: "事实",
      note: null,
      reason: "来源图片里有标注",
      status: "pending",
      recommended_node_id: 9,
      node_reason: "属于水电定位",
      routing_status: "done",
      relation_status: "done",
      new_node_suggestion: null,
      node_alternatives: [],
    },
  ]);

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));

  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());
  expect(screen.getByText("水电定位时拍的")).toBeTruthy();
  expect(screen.getByText("识别到的现场文字")).toBeTruthy();
  expect(screen.getByText("插座底边离地 30 厘米")).toBeTruthy();
  expect(screen.getByText("AI 候选")).toBeTruthy();

  const labels = buttonLabels(screen);
  expect(labels).toEqual([
    "返回收集列表",
    "放大查看第 1 张：a.jpg",
    "改归属",
    "删除",
  ]);
  for (const forbidden of ["采纳", "拒绝", "写入", "归档", "确认候选"]) {
    expect(labels.some((label) => label.includes(forbidden))).toBe(false);
  }
  expect(screen.queryByText("建议新增节点")).toBeNull();
});

test("改归属：锁定来源只给阻断说明，不渲染项目选项", async () => {
  mockListSources.mockResolvedValue([source({ id: 1, project_locked: true, status: "done" })]);
  mockGetSource.mockResolvedValue(source({ id: 1, project_locked: true, status: "done" }));

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  fireEvent.press(screen.getByLabelText("改归属"));

  await waitFor(() => expect(screen.getByText("不能修改归属")).toBeTruthy());
  expect(screen.getByText(/如需移动，请先到桌面工作台处理关联的正式知识/)).toBeTruthy();
  expect(screen.queryByRole("radio")).toBeNull();
  expect(mockUpdateSourceProject).not.toHaveBeenCalled();
});

test("改归属：服务端 409 兜底并原样展示文案", async () => {
  mockListSources.mockResolvedValue([source({ id: 1, status: "done" })]);
  mockGetSource.mockResolvedValue(source({ id: 1, status: "done" }));
  mockGetProjects.mockResolvedValue([{ id: 3, name: "新房装修", description: null, status: "active" }]);
  mockUpdateSourceProject.mockRejectedValue(conflictError("该来源已被正式知识引用，如需移动请先处理关联 Entry"));

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  fireEvent.press(screen.getByLabelText("改归属"));
  await waitFor(() => expect(screen.getByLabelText("新房装修")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("新房装修"));

  await waitFor(() =>
    expect(
      screen.getByText("该来源已被正式知识引用，如需移动请先处理关联 Entry"),
    ).toBeTruthy(),
  );
});

test("改归属成功后提交 project_id 并刷新列表", async () => {
  mockListSources.mockResolvedValue([source({ id: 1, status: "done" })]);
  mockGetSource.mockResolvedValue(source({ id: 1, status: "done" }));
  mockGetProjects.mockResolvedValue([{ id: 3, name: "新房装修", description: null, status: "active" }]);

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  fireEvent.press(screen.getByLabelText("改归属"));
  await waitFor(() => expect(screen.getByLabelText("新房装修")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("新房装修"));

  await waitFor(() => expect(mockUpdateSourceProject).toHaveBeenCalledWith("token", 1, 3));
  await flushAsyncWork();
  // 改归属成功后列表与详情都要重新取数
  expect(mockListSources.mock.calls.length).toBeGreaterThan(1);
  expect(mockGetSource.mock.calls.length).toBeGreaterThan(1);
});

test("删除：处理中被阻止，不提供确认删除", async () => {
  mockListSources.mockResolvedValue([source({ id: 1, status: "processing" })]);
  mockGetSource.mockResolvedValue(source({ id: 1, status: "processing" }));

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  fireEvent.press(screen.getByLabelText("删除"));

  await waitFor(() => expect(screen.getByText("不能删除")).toBeTruthy());
  expect(screen.getByText(/正在处理中/)).toBeTruthy();
  expect(screen.queryByLabelText("确认删除")).toBeNull();
  expect(screen.queryByText(/无法恢复/)).toBeNull();
});

test("删除：有待确认候选时二次确认说明会一并移除，确认后关闭详情并刷新", async () => {
  mockListSources.mockResolvedValue([
    source({ id: 1, status: "done", pending_candidate_count: 2 }),
  ]);
  mockGetSource.mockResolvedValue(source({ id: 1, status: "done", pending_candidate_count: 2 }));

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  fireEvent.press(screen.getByLabelText("删除"));
  await waitFor(() => expect(screen.getByText(/将一并移除这些候选/)).toBeTruthy());

  fireEvent.press(screen.getByLabelText("确认删除"));

  await waitFor(() => expect(mockDeleteSource).toHaveBeenCalledWith("token", 1));
  await waitFor(() => expect(screen.queryByText("来源详情")).toBeNull());
  await flushAsyncWork();
  expect(mockListSources.mock.calls.length).toBeGreaterThan(1);
});

test("删除失败时保留详情并原样展示服务端文案", async () => {
  mockListSources.mockResolvedValue([source({ id: 1, status: "done" })]);
  mockGetSource.mockResolvedValue(source({ id: 1, status: "done" }));
  mockDeleteSource.mockRejectedValue(conflictError("该来源已被正式知识引用，不能删除；请先处理关联 Entry"));

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  fireEvent.press(screen.getByLabelText("删除"));
  await waitFor(() => expect(screen.getByLabelText("确认删除")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("确认删除"));

  await waitFor(() =>
    expect(
      screen.getByText("该来源已被正式知识引用，不能删除；请先处理关联 Entry"),
    ).toBeTruthy(),
  );
  expect(screen.getByText("来源详情")).toBeTruthy();
});
