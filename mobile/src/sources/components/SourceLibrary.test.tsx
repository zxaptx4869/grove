/**
 * 收集箱栏目入口页的来源库集成：列表四态、筛选、失败重试、只读详情、改归属与删除。
 * 全部通过 mock 的接口数据驱动，不依赖真机或模拟器。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, waitFor, within } from "@testing-library/react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { CaptureScreen } from "@/src/capture/components/CaptureScreen";
import { formatSourceTime } from "@/src/sources/state";
import type { SourceOut } from "@/src/sources/types";

const mockListSources = jest.fn(async (..._args: unknown[]): Promise<unknown> => []);
const mockGetSource = jest.fn(async (..._args: unknown[]): Promise<unknown> => null);
const mockListCandidates = jest.fn(async (..._args: unknown[]): Promise<unknown> => []);
const mockUpdateSourceProject = jest.fn(async (..._args: unknown[]): Promise<unknown> => null);
const mockDeleteSource = jest.fn(async (..._args: unknown[]): Promise<unknown> => ({ ok: true }));
const mockTriggerProcessing = jest.fn(async (..._args: unknown[]): Promise<unknown> => undefined);
const mockGetProjects = jest.fn(async (..._args: unknown[]): Promise<unknown> => []);
const mockDownloadFileAsync = jest.fn(async (..._args: unknown[]): Promise<unknown> => ({
  uri: "file://cache/source-1-11.jpg",
}));

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
jest.mock("expo-file-system", () => {
  class MockFile {
    uri: string;
    name: string;
    type = "image/jpeg";
    constructor(...parts: unknown[]) {
      const last = parts[parts.length - 1];
      this.name = String(last);
      this.uri =
        typeof last === "string" && last.startsWith("file://")
          ? last
          : `file://cache/${String(last)}`;
    }
    exists = false;
    info() {
      return { size: 1024 };
    }
    delete() {
      this.exists = false;
    }
    async bytes() {
      return new Uint8Array();
    }
    static downloadFileAsync = (...args: unknown[]) => mockDownloadFileAsync(...args);
  }
  class MockDirectory {
    list() {
      return [];
    }
  }
  return { File: MockFile, Directory: MockDirectory, Paths: { cache: "file://cache" } };
});
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
/** 读取「确认修改」的禁用态：弹层里的确认入口只在选了不同归属时可用。 */
function confirmDisabled(target: { getByLabelText: (label: string) => { props: { accessibilityState?: { disabled?: boolean } } } }) {
  return target.getByLabelText("确认修改").props.accessibilityState?.disabled ?? false;
}

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
  mockDownloadFileAsync.mockResolvedValue({ uri: "file://cache/source-1-11.jpg" });
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

test("筛选标签不显示按当前窗口现算的条数", async () => {
  mockListSources.mockResolvedValue([
    source({ id: 1, title: "第一条" }),
    source({ id: 2, title: "第二条" }),
  ]);

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("第一条")).toBeTruthy());

  // 列表只取最近 20 条，按窗口现算的条数会随筛选切换而变（切到未归属后两个标签变成同一个数），
  // 属于误导信息，因此筛选标签只显示文字
  const allTab = within(screen.getByLabelText("全部"));
  const unassignedTab = within(screen.getByLabelText("未归属"));
  expect(allTab.getByText("全部")).toBeTruthy();
  expect(unassignedTab.getByText("未归属")).toBeTruthy();
  expect(allTab.queryByText(/\d/)).toBeNull();
  expect(unassignedTab.queryByText(/\d/)).toBeNull();
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

test("详情：创建时间与列表同一口径，不出现原始 ISO 串", async () => {
  const iso = "2026-09-24T02:12:00.000Z";
  mockListSources.mockResolvedValue([source({ id: 1, status: "done", created_at: iso })]);
  mockGetSource.mockResolvedValue(source({ id: 1, status: "done", created_at: iso }));

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  // 列表行的材料与时间共用同一个 Text（「1 张图片 · 9 月 24 日 10:12」），按子串匹配
  expect(screen.getByText(formatSourceTime(iso), { exact: false })).toBeTruthy();
  expect(screen.queryByText(/\d{4}-\d{2}-\d{2}T\d{2}:/)).toBeNull();

  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());
  expect(screen.getByText("创建时间")).toBeTruthy();
  // 详情里的时间独占一行，必须是列表同一口径的格式化文案，而不是原始 ISO 串
  expect(screen.getAllByText(formatSourceTime(iso)).length).toBeGreaterThan(0);
  expect(screen.queryByText(/\d{4}-\d{2}-\d{2}T\d{2}:/)).toBeNull();
});

test("详情：附件图片的缓存名带上来源版本，库重置后不复用同号旧文件", async () => {
  mockListSources.mockResolvedValue([source({ id: 1, status: "done" })]);
  mockGetSource.mockResolvedValue(source({ id: 1, status: "done" }));

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  await waitFor(() => expect(mockDownloadFileAsync).toHaveBeenCalled());
  const target = mockDownloadFileAsync.mock.calls[0][1] as { name: string };
  expect(target.name).toBe("grove-source-1-11-20260924T021200000Z.jpg");
});

test("详情：多张图时左右滑动切换，到头停住", async () => {
  const multi = source({
    id: 1,
    status: "done",
    attachments: [
      { id: 11, kind: "image", position: 0, mime_type: "image/jpeg", file_name: "a.jpg", text_content: null, ocr_text: null },
      { id: 12, kind: "image", position: 1, mime_type: "image/jpeg", file_name: "b.jpg", text_content: null, ocr_text: null },
    ],
  });
  mockListSources.mockResolvedValue([multi]);
  mockGetSource.mockResolvedValue(multi);

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  fireEvent.press(screen.getByLabelText("放大查看第 1 张：a.jpg"));
  await waitFor(() => expect(screen.getByText("第 1 / 2 张")).toBeTruthy());
  expect(screen.getByText("双指缩放 · 双击放大 / 还原 · 左右滑动切换")).toBeTruthy();

  // 手指向左滑 = 看下一张
  const swipe = async (from: number, to: number) => {
    const viewport = screen.getByTestId("zoomable-image-viewport");
    const event = (pageX: number) => ({ nativeEvent: { touches: [{ pageX, pageY: 300 }] } });
    await act(async () => {
      viewport.props.onTouchStart(event(from));
      viewport.props.onTouchMove(event(to));
      viewport.props.onTouchEnd({ nativeEvent: { touches: [] } });
    });
  };

  await swipe(300, 140);
  await waitFor(() => expect(screen.getByText("第 2 / 2 张")).toBeTruthy());
  expect(screen.getByLabelText("第 2 张原图")).toBeTruthy();

  // 已经在最后一张，继续向左滑停在原地
  await swipe(300, 140);
  await waitFor(() => expect(screen.getByText("第 2 / 2 张")).toBeTruthy());

  // 向右滑回到上一张
  await swipe(140, 300);
  await waitFor(() => expect(screen.getByText("第 1 / 2 张")).toBeTruthy());
});

test("详情：放大查看打开原图视图，给出缩放提示与文件名，关闭后回到详情", async () => {
  mockListSources.mockResolvedValue([source({ id: 1, status: "done" })]);
  mockGetSource.mockResolvedValue(source({ id: 1, status: "done" }));

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  fireEvent.press(screen.getByLabelText("放大查看第 1 张：a.jpg"));
  await waitFor(() => expect(screen.getByText("第 1 / 1 张")).toBeTruthy());
  expect(screen.getByText("双指缩放 · 双击放大 / 还原")).toBeTruthy();
  expect(screen.getByText("a.jpg")).toBeTruthy();
  expect(screen.getByLabelText("第 1 张原图")).toBeTruthy();
  expect(screen.getByTestId("zoomable-image-content")).toBeTruthy();

  fireEvent.press(screen.getByLabelText("关闭原图"));
  await waitFor(() => expect(screen.queryByText("第 1 / 1 张")).toBeNull());
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
    "返回收集箱列表",
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
  await waitFor(() => expect(confirmDisabled(screen)).toBe(false));
  fireEvent.press(screen.getByLabelText("确认修改"));

  await waitFor(() =>
    expect(
      screen.getByText("该来源已被正式知识引用，如需移动请先处理关联 Entry"),
    ).toBeTruthy(),
  );
  expect(screen.getByLabelText("新房装修").props.accessibilityState.checked).toBe(true);
  // 失败保留弹层：项目选项与确认入口都还在
  expect(screen.getByLabelText("新房装修")).toBeTruthy();
  expect(screen.getByLabelText("确认修改")).toBeTruthy();
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
  await waitFor(() => expect(confirmDisabled(screen)).toBe(false));
  fireEvent.press(screen.getByLabelText("确认修改"));

  await waitFor(() => expect(mockUpdateSourceProject).toHaveBeenCalledWith("token", 1, 3));
  await flushAsyncWork();
  // 改归属成功后列表与详情都要重新取数
  expect(mockListSources.mock.calls.length).toBeGreaterThan(1);
  expect(mockGetSource.mock.calls.length).toBeGreaterThan(1);
});

test("改归属：点选只改选择态，点「确认修改」才提交", async () => {
  mockListSources.mockResolvedValue([source({ id: 1, status: "done" })]);
  mockGetSource.mockResolvedValue(source({ id: 1, status: "done" }));
  mockGetProjects.mockResolvedValue([{ id: 3, name: "新房装修", description: null, status: "active" }]);

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  fireEvent.press(screen.getByLabelText("改归属"));
  await waitFor(() => expect(screen.getByLabelText("新房装修")).toBeTruthy());

  // 初始选择就是当前归属（未归属），确认入口不可用
  expect(screen.getByLabelText("确认修改").props.accessibilityState.disabled).toBe(true);

  fireEvent.press(screen.getByLabelText("新房装修"));
  await waitFor(() => expect(confirmDisabled(screen)).toBe(false));

  expect(mockUpdateSourceProject).not.toHaveBeenCalled();
  expect(screen.getByLabelText("新房装修").props.accessibilityState.checked).toBe(true);

  // 选回当前归属，确认入口再次不可用，且始终没有写请求
  fireEvent.press(screen.getByLabelText("未归属"));
  await waitFor(() => expect(confirmDisabled(screen)).toBe(true));

  expect(mockUpdateSourceProject).not.toHaveBeenCalled();
});

test("改归属：提交期间显示进行中状态并禁用选项与按钮", async () => {
  mockListSources.mockResolvedValue([source({ id: 1, status: "done" })]);
  mockGetSource.mockResolvedValue(source({ id: 1, status: "done" }));
  mockGetProjects.mockResolvedValue([{ id: 3, name: "新房装修", description: null, status: "active" }]);
  let resolveMove: () => void = () => undefined;
  mockUpdateSourceProject.mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveMove = () => resolve({ id: 1 });
      }),
  );

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  fireEvent.press(screen.getByLabelText("改归属"));
  await waitFor(() => expect(screen.getByLabelText("新房装修")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("新房装修"));
  await waitFor(() => expect(confirmDisabled(screen)).toBe(false));
  fireEvent.press(screen.getByLabelText("确认修改"));

  await waitFor(() => expect(screen.getByLabelText("正在更换…")).toBeTruthy());
  expect(screen.getByText("正在更换项目并重新推荐目录，请稍候…")).toBeTruthy();
  expect(screen.getByLabelText("新房装修").props.accessibilityState.disabled).toBe(true);
  expect(screen.getByLabelText("取消").props.accessibilityState.disabled).toBe(true);

  // 重复点击不会再次提交
  fireEvent.press(screen.getByLabelText("正在更换…"));
  expect(mockUpdateSourceProject).toHaveBeenCalledTimes(1);

  await act(async () => {
    resolveMove();
  });
  await waitFor(() => expect(screen.queryByText("正在更换项目并重新推荐目录，请稍候…")).toBeNull());
});

test("原始材料图片：读取失败给出重试入口，重试成功后渲染本地缓存文件", async () => {
  const warn = jest.spyOn(console, "warn").mockImplementation(() => undefined);
  mockListSources.mockResolvedValue([source({ id: 1, status: "done" })]);
  mockGetSource.mockResolvedValue(source({ id: 1, status: "done" }));
  mockDownloadFileAsync.mockRejectedValueOnce(new Error("UnableToDownload: 401"));

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  // 图片读取失败不静默留白：给出失败提示与重试入口，详情其余内容仍可读
  await waitFor(() => expect(screen.getByText("图片读取失败")).toBeTruthy());
  expect(screen.getByLabelText("重试读取图片：a.jpg")).toBeTruthy();
  expect(screen.getByText("候选的确认、拒绝与写入在桌面工作台或对话里完成，这里只读。")).toBeTruthy();

  fireEvent.press(screen.getByLabelText("重试读取图片：a.jpg"));
  await waitFor(() => expect(screen.queryByText("图片读取失败")).toBeNull());
  expect(mockDownloadFileAsync).toHaveBeenCalledTimes(2);

  // 图片走带认证头的下载通道：地址是附件端点，鉴权头必须真的传下去
  // （此前依赖 Image 自带请求头，Expo Go 下不会发出，附件端点收到 401）
  const [url, , options] = mockDownloadFileAsync.mock.calls[1] as [
    string,
    unknown,
    { headers?: Record<string, string> },
  ];
  expect(url).toBe("http://api.test/api/sources/1/attachments/11/file");
  expect(options.headers).toEqual({ Authorization: "Bearer token" });
  warn.mockRestore();
});

test("删除：提交期间进度落在确认按钮上，不再插入「正在删除…」提示行", async () => {
  mockListSources.mockResolvedValue([source({ id: 1, status: "done" })]);
  mockGetSource.mockResolvedValue(source({ id: 1, status: "done" }));
  let resolveDelete: () => void = () => undefined;
  mockDeleteSource.mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveDelete = () => resolve({ id: 1 });
      }),
  );

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  fireEvent.press(screen.getByLabelText("删除"));
  await waitFor(() => expect(screen.getByLabelText("确认删除")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("确认删除"));

  // 进行中：确认按钮变为「删除中…」，且没有额外的提示行撑高弹层
  await waitFor(() => expect(screen.getByLabelText("删除中…")).toBeTruthy());
  expect(screen.queryByLabelText("确认删除")).toBeNull();
  expect(screen.queryByText("正在删除…")).toBeNull();
  expect(screen.getByLabelText("取消").props.accessibilityState.disabled).toBe(true);

  // 重复点击不会再次提交
  fireEvent.press(screen.getByLabelText("删除中…"));
  expect(mockDeleteSource).toHaveBeenCalledTimes(1);

  await act(async () => {
    resolveDelete();
  });
  await waitFor(() => expect(screen.queryByText("来源详情")).toBeNull());
  await flushAsyncWork();
  expect(mockListSources.mock.calls.length).toBeGreaterThan(1);
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

test("删除：服务端 409 仍按阻断展示，不给重试入口", async () => {
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
  expect(screen.getByText("不能删除")).toBeTruthy();
  expect(screen.queryByLabelText("重试删除")).toBeNull();
  expect(screen.getByLabelText("知道了")).toBeTruthy();
  expect(screen.getByText("来源详情")).toBeTruthy();
});

test("删除：网络失败给出「删除失败」与重试入口，重试会再次发起删除", async () => {
  mockListSources.mockResolvedValue([source({ id: 1, status: "done" })]);
  mockGetSource.mockResolvedValue(source({ id: 1, status: "done" }));
  mockDeleteSource.mockRejectedValueOnce(new Error("Network request failed"));
  mockDeleteSource.mockResolvedValueOnce({ ok: true });

  const screen = await renderScreen();
  await waitFor(() => expect(screen.getByText("厨房插座位置确认")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("查看来源详情：厨房插座位置确认"));
  await waitFor(() => expect(screen.getByText("来源详情")).toBeTruthy());

  fireEvent.press(screen.getByLabelText("删除"));
  await waitFor(() => expect(screen.getByLabelText("确认删除")).toBeTruthy());
  fireEvent.press(screen.getByLabelText("确认删除"));

  // 失败不是死胡同：标题说明是本次失败，并保留重试入口
  await waitFor(() => expect(screen.getByText("删除失败")).toBeTruthy());
  expect(screen.getByText("网络连接中断，请检查网络后重试。")).toBeTruthy();
  expect(mockDeleteSource).toHaveBeenCalledTimes(1);

  fireEvent.press(screen.getByLabelText("重试删除"));
  await waitFor(() => expect(mockDeleteSource).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.queryByText("来源详情")).toBeNull());
  await flushAsyncWork();
  expect(mockListSources.mock.calls.length).toBeGreaterThan(1);
});
