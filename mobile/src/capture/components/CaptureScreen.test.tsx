import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react-native";
import * as ImagePicker from "expo-image-picker";
import { Linking } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { CaptureScreen } from "@/src/capture/components/CaptureScreen";
import { installExpoFetchFormData } from "@/src/capture/testing/expo-fetch-formdata";

const mockGetProjects = jest.fn(async () => []);
const mockRequest = jest.fn(async (..._args: unknown[]) => ({ id: 1 }));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ token: "token", me: null }),
}));

jest.mock("@/src/api", () => ({
  apiBaseUrl: "http://api.test",
  apiConfigured: true,
  getProjects: () => mockGetProjects(),
  request: (...args: unknown[]) => mockRequest(...args),
}));

jest.mock("expo-crypto", () => ({ randomUUID: () => "batch-uuid" }));
jest.mock("expo-clipboard", () => ({ getStringAsync: jest.fn(async () => "剪贴板里的文字") }));

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

jest.mock("expo-image-picker", () => ({
  getCameraPermissionsAsync: jest.fn(),
  requestCameraPermissionsAsync: jest.fn(),
  getMediaLibraryPermissionsAsync: jest.fn(),
  requestMediaLibraryPermissionsAsync: jest.fn(),
  launchCameraAsync: jest.fn(),
  launchImageLibraryAsync: jest.fn(),
}));

jest.mock("expo-image-manipulator", () => {
  const context: { resize: jest.Mock; renderAsync: jest.Mock } = {
    resize: jest.fn(),
    renderAsync: jest.fn(),
  };
  context.resize.mockReturnValue(context);
  return {
    SaveFormat: { JPEG: "jpeg" },
    ImageManipulator: { manipulate: jest.fn(() => context) },
    // 暴露给用例：压缩的时机与挂起都由它控制
    __context: context,
  };
});

const picker = ImagePicker as jest.Mocked<typeof ImagePicker>;
const manipulator = (
  jest.requireMock("expo-image-manipulator") as {
    __context: { resize: jest.Mock; renderAsync: jest.Mock };
  }
).__context;

/** 压缩结果的默认替身：成功返回本地 jpg 副本。 */
function stubPreparedImage() {
  manipulator.renderAsync.mockImplementation(async () => ({
    saveAsync: async () => ({ uri: "file://grove.jpg", width: 2048, height: 1536 }),
  }));
}
const originalFetch = globalThis.fetch;

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

function asset(uri: string) {
  return {
    uri,
    width: 4000,
    height: 3000,
    fileName: "IMG_0001.HEIC",
    mimeType: "image/heic",
    fileSize: 10,
  } as unknown as ImagePicker.ImagePickerAsset;
}

/** 从入口页进入相册「每张一条」采集页并选中 3 张图。 */
async function openAlbumSeparate(screen: Awaited<ReturnType<typeof renderScreen>>) {
  picker.getMediaLibraryPermissionsAsync.mockResolvedValue({ granted: true } as never);
  picker.launchImageLibraryAsync.mockResolvedValue({
    canceled: false,
    assets: [asset("file://1.heic"), asset("file://2.heic"), asset("file://3.heic")],
  } as never);
  await fireEvent.press(screen.getByLabelText("相册采集"));
  await fireEvent.press(await screen.findByLabelText(/每张一条/));
  await waitFor(() => expect(screen.getByText(/这 3 张将分别作为 3 条材料提交/)).toBeTruthy());
}

let restoreFormData: () => void;

beforeEach(() => {
  restoreFormData = installExpoFetchFormData();
  jest.clearAllMocks();
  manipulator.renderAsync.mockReset();
  stubPreparedImage();
  mockGetProjects.mockResolvedValue([]);
  mockRequest.mockResolvedValue({ id: 1 });
});

afterEach(() => {
  cleanup();
  restoreFormData();
  globalThis.fetch = originalFetch;
});

function stubUpload(id = 21) {
  globalThis.fetch = jest.fn(async () => ({
    ok: true,
    status: 201,
    json: async () => ({ id }),
  })) as unknown as typeof fetch;
}

/** 从入口页进入文字采集页并填入剪贴板文字。 */
async function openTextWithClipboard(screen: Awaited<ReturnType<typeof renderScreen>>) {
  await fireEvent.press(screen.getByLabelText("文本采集"));
  await fireEvent.press(await screen.findByLabelText("从剪贴板填入"));
  await waitFor(() => expect(screen.getByDisplayValue("剪贴板里的文字")).toBeTruthy());
}

test("入口页只有三入口，不渲染表单与提交条", async () => {
  const screen = await renderScreen();

  expect(screen.getByLabelText("相机采集")).toBeTruthy();
  expect(screen.getByLabelText("相册采集")).toBeTruthy();
  expect(screen.getByLabelText("文本采集")).toBeTruthy();
  expect(screen.queryByLabelText("补充说明")).toBeNull();
  expect(screen.queryByLabelText("提交采集")).toBeNull();
  expect(screen.queryByLabelText("提交状态")).toBeNull();
});

test("进入采集页后入口行消失，返回会丢弃草稿", async () => {
  const screen = await renderScreen();

  await fireEvent.press(screen.getByLabelText("文本采集"));
  expect(screen.getByText("文字采集")).toBeTruthy();
  expect(screen.queryByLabelText("相机采集")).toBeNull();

  await fireEvent.press(await screen.findByLabelText("从剪贴板填入"));
  await waitFor(() => expect(screen.getByDisplayValue("剪贴板里的文字")).toBeTruthy());

  await fireEvent.press(screen.getByLabelText("返回收集列表"));
  expect(screen.getByLabelText("相机采集")).toBeTruthy();
  expect(screen.queryByLabelText("补充说明")).toBeNull();

  // 重新进入是一次全新的空草稿：文字已清空，提交条按原型处于禁用态
  await fireEvent.press(screen.getByLabelText("文本采集"));
  expect(screen.queryByDisplayValue("剪贴板里的文字")).toBeNull();
  expect(screen.getByText("先填入文字，再提交")).toBeTruthy();
  expect(screen.getByLabelText("提交采集")).toBeDisabled();
});

test("全部成功时停留在结果页，由底部按钮回到收集", async () => {
  stubUpload();
  const screen = await renderScreen();

  await openTextWithClipboard(screen);
  await fireEvent.press(screen.getByLabelText("提交采集"));

  // 不自动关闭、不自动跳转：覆盖层停在成功汇总，底部固定区域给出返回入口
  await waitFor(() => expect(screen.getByText("已提交 1 条")).toBeTruthy());
  expect(screen.getByLabelText("提交状态")).toBeTruthy();
  expect(screen.getByText(/桌面工作台/)).toBeTruthy();
  expect(screen.getByLabelText("回到收集")).toBeTruthy();
  expect(screen.queryByLabelText("相机采集")).toBeNull();

  await fireEvent.press(screen.getByLabelText("回到收集"));
  expect(screen.getByLabelText("相机采集")).toBeTruthy();
  expect(screen.queryByLabelText("提交状态")).toBeNull();

  // 草稿、会话与批次键都清空：重新进入是空草稿
  await fireEvent.press(screen.getByLabelText("文本采集"));
  expect(screen.queryByDisplayValue("剪贴板里的文字")).toBeNull();
  expect(screen.getByText("先填入文字，再提交")).toBeTruthy();
});

test("处理未启动时仍算已提交，并在卡片内给出提示", async () => {
  stubUpload();
  mockRequest.mockRejectedValue(new Error("处理服务不可用"));
  const screen = await renderScreen();

  await openTextWithClipboard(screen);
  await fireEvent.press(screen.getByLabelText("提交采集"));

  await waitFor(() => expect(screen.getByText("已提交 1 条")).toBeTruthy());
  expect(screen.getByLabelText("提交状态")).toBeTruthy();
  expect(screen.getByText(/来源已保存，但处理启动失败（处理服务不可用）/)).toBeTruthy();
  expect(screen.getByLabelText("回到收集")).toBeTruthy();
});

test("存在失败时覆盖层停留，逐条重试沿用同键且重试后仍停在结果页", async () => {
  const keys: string[] = [];
  globalThis.fetch = jest.fn(async (_url: string, init: RequestInit) => {
    const posted = init.body as FormData;
    keys.push(String(posted.get("capture_key")));
    if (keys.length === 3) {
      return { ok: false, status: 400, json: async () => ({ detail: "仅支持 png、jpg、webp 图片" }) };
    }
    return { ok: true, status: 201, json: async () => ({ id: keys.length }) };
  }) as unknown as typeof fetch;
  const screen = await renderScreen();

  await openAlbumSeparate(screen);
  await fireEvent.press(screen.getByLabelText("提交采集"));

  await waitFor(() => expect(screen.getByText("已提交 2 条，1 条未成功")).toBeTruthy());
  expect(screen.getByText("提交未成功")).toBeTruthy();
  expect(keys).toEqual(["batch-uuid:1", "batch-uuid:2", "batch-uuid:3"]);
  expect(screen.getByText("仅支持 png、jpg、webp 图片")).toBeTruthy();

  // 只重试失败项并沿用同一个键；重试成功后仍停在结果页，汇总变成全部成功
  await fireEvent.press(screen.getByLabelText("重试这一条"));
  await waitFor(() => expect(screen.getByText("已提交 3 条")).toBeTruthy());
  expect(keys).toEqual(["batch-uuid:1", "batch-uuid:2", "batch-uuid:3", "batch-uuid:3"]);
  expect(screen.getByLabelText("提交状态")).toBeTruthy();
  expect(screen.getByLabelText("回到收集")).toBeTruthy();
});

test("全部失败时停在结果页，回到收集后回入口页并清空", async () => {
  globalThis.fetch = jest.fn(async () => ({
    ok: false,
    status: 503,
    json: async () => ({ detail: "服务暂时不可用" }),
  })) as unknown as typeof fetch;
  const screen = await renderScreen();

  await openTextWithClipboard(screen);
  await fireEvent.press(screen.getByLabelText("提交采集"));

  await waitFor(() => expect(screen.getByText("已提交 0 条，1 条未成功")).toBeTruthy());
  expect(screen.getByLabelText("提交状态")).toBeTruthy();
  await fireEvent.press(screen.getByLabelText("回到收集"));

  expect(screen.getByLabelText("相机采集")).toBeTruthy();
  expect(screen.queryByLabelText("提交状态")).toBeNull();
  await fireEvent.press(screen.getByLabelText("文本采集"));
  expect(screen.queryByDisplayValue("剪贴板里的文字")).toBeNull();
});

test("服务端 400 仍在覆盖层逐条显示原文，不回采集页", async () => {
  globalThis.fetch = jest.fn(async () => ({
    ok: false,
    status: 400,
    json: async () => ({ detail: "仅支持 png、jpg、webp 图片" }),
  })) as unknown as typeof fetch;
  const screen = await renderScreen();

  await openTextWithClipboard(screen);
  await fireEvent.press(screen.getByLabelText("提交采集"));

  await waitFor(() => expect(screen.getByText("已提交 0 条，1 条未成功")).toBeTruthy());
  expect(screen.getByLabelText("提交状态")).toBeTruthy();
  expect(screen.getByText("仅支持 png、jpg、webp 图片")).toBeTruthy();
  // 表单页仍在覆盖层之下，但没有出现「材料没有保存」的表单内错误卡
  expect(screen.queryByText("材料没有保存到 Grove，已填写的内容仍在表单里。")).toBeNull();
});

test("提交进行中底部没有回到收集，返回键也不关闭覆盖层", async () => {
  globalThis.fetch = jest.fn(() => new Promise(() => {})) as unknown as typeof fetch;
  const screen = await renderScreen();

  await openAlbumSeparate(screen);
  await fireEvent.press(screen.getByLabelText("提交采集"));

  await waitFor(() => expect(screen.getByText("正在上传 3 张中的第 1 张…")).toBeTruthy());
  expect(screen.getByLabelText("提交状态")).toBeTruthy();
  expect(screen.queryByLabelText("回到收集")).toBeNull();

  // 返回键（Modal onRequestClose）不关闭覆盖层
  await fireEvent(screen.getByLabelText("提交状态"), "requestClose");
  expect(screen.getByLabelText("提交状态")).toBeTruthy();
});

test("选完图片直接进采集页，压缩留到提交时才做", async () => {
  stubUpload();
  const screen = await renderScreen();

  await openAlbumSeparate(screen);

  // 采集页立刻可用：不出现任何准备中提示，也还没有调用压缩
  expect(screen.queryByText(/正在压缩/)).toBeNull();
  expect(manipulator.renderAsync).not.toHaveBeenCalled();
});

test("压缩过程呈现在提交覆盖层里，压缩完才上传", async () => {
  stubUpload();
  let release: (() => void) | null = null;
  manipulator.renderAsync.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        release = () =>
          resolve({
            saveAsync: async () => ({ uri: "file://grove.jpg", width: 2048, height: 1536 }),
          });
      }),
  );
  const screen = await renderScreen();

  await openAlbumSeparate(screen);
  await fireEvent.press(screen.getByLabelText("提交采集"));

  await waitFor(() => expect(screen.getByText("正在压缩 3 张中的第 1 张…")).toBeTruthy());
  expect(screen.getByLabelText("提交状态")).toBeTruthy();
  expect(screen.getByText("正在压缩图片")).toBeTruthy();
  expect(globalThis.fetch).not.toHaveBeenCalled();

  (release as unknown as () => void)();
  await waitFor(() => expect(screen.getByText("已提交 3 条")).toBeTruthy());
  expect(globalThis.fetch).toHaveBeenCalledTimes(3);
});

test("单张压缩失败只标记该条，其余继续上传", async () => {
  stubUpload();
  manipulator.renderAsync.mockImplementationOnce(() =>
    Promise.reject(new Error("Failed to load image")),
  );
  const screen = await renderScreen();

  await openAlbumSeparate(screen);
  await fireEvent.press(screen.getByLabelText("提交采集"));

  await waitFor(() => expect(screen.getByText("已提交 2 条，1 条未成功")).toBeTruthy());
  expect(screen.getByText("图片处理失败，请重新选择。")).toBeTruthy();
  expect(screen.queryByText("Failed to load image")).toBeNull();
  expect(globalThis.fetch).toHaveBeenCalledTimes(2);
});

test("连点提交只跑一次，不会重复上传同一批", async () => {
  const fetchMock = jest.fn(() => new Promise(() => {}));
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  const screen = await renderScreen();

  await openTextWithClipboard(screen);
  const submit = screen.getByLabelText("提交采集");
  await fireEvent.press(submit);
  await fireEvent.press(submit);

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  expect(screen.getByLabelText("提交状态")).toBeTruthy();
});

test("相机权限被拒时进入独立权限页，可去设置", async () => {
  picker.getCameraPermissionsAsync.mockResolvedValue({ granted: false } as never);
  picker.requestCameraPermissionsAsync.mockResolvedValue({ granted: false } as never);
  const openSettings = jest.spyOn(Linking, "openSettings").mockResolvedValue(undefined as never);
  const screen = await renderScreen();

  await fireEvent.press(screen.getByLabelText("相机采集"));

  expect(screen.getByText("相机权限")).toBeTruthy();
  expect(screen.getByText("无法使用相机")).toBeTruthy();
  expect(screen.getByText(/系统不会再重复弹出授权提示/)).toBeTruthy();
  expect(screen.queryByLabelText("相机采集")).toBeNull();
  expect(picker.launchCameraAsync).not.toHaveBeenCalled();

  await fireEvent.press(screen.getByLabelText("去设置"));
  expect(openSettings).toHaveBeenCalledTimes(1);

  await fireEvent.press(screen.getByLabelText("返回收集"));
  expect(screen.getByLabelText("相机采集")).toBeTruthy();
});

test("相册权限被拒时给出说明且不打开选择器", async () => {
  picker.getMediaLibraryPermissionsAsync.mockResolvedValue({ granted: false } as never);
  picker.requestMediaLibraryPermissionsAsync.mockResolvedValue({ granted: false } as never);
  const screen = await renderScreen();

  await fireEvent.press(screen.getByLabelText("相册采集"));

  expect(screen.getByText("无法访问相册")).toBeTruthy();
  expect(picker.launchImageLibraryAsync).not.toHaveBeenCalled();
});

test("文本采集从剪贴板填入并携带幂等键提交", async () => {
  let form: FormData | null = null;
  globalThis.fetch = jest.fn(async (_url: string, init: RequestInit) => {
    form = init.body as FormData;
    return { ok: true, status: 201, json: async () => ({ id: 21 }) };
  }) as unknown as typeof fetch;
  const screen = await renderScreen();

  await openTextWithClipboard(screen);
  await fireEvent.press(screen.getByLabelText("提交采集"));

  await waitFor(() => expect(screen.getByText("已提交 1 条")).toBeTruthy());
  expect(form!.get("text")).toBe("剪贴板里的文字");
  expect(form!.get("capture_key")).toBe("batch-uuid:1");
  expect(mockRequest).toHaveBeenCalledWith("/api/sources/21/process", { method: "POST" }, "token");
});
