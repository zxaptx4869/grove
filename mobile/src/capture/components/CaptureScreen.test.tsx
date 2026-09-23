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
jest.mock("expo-clipboard", () => ({ getStringAsync: jest.fn(async () => "剪贴板里的文字") }));

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
    renderAsync: jest.fn(async () => ({
      saveAsync: jest.fn(async () => ({ uri: "file://grove.jpg", width: 2048, height: 1536 })),
    })),
  };
  context.resize.mockReturnValue(context);
  return { SaveFormat: { JPEG: "jpeg" }, ImageManipulator: { manipulate: jest.fn(() => context) } };
});

const picker = ImagePicker as jest.Mocked<typeof ImagePicker>;
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
  return { uri, width: 4000, height: 3000, fileName: null, fileSize: 10 } as unknown as ImagePicker.ImagePickerAsset;
}

let restoreFormData: () => void;

beforeEach(() => {
  restoreFormData = installExpoFetchFormData();
  jest.clearAllMocks();
  mockGetProjects.mockResolvedValue([]);
  mockRequest.mockResolvedValue({ id: 1 });
});

afterEach(() => {
  cleanup();
  restoreFormData();
  globalThis.fetch = originalFetch;
});

test("相机权限被拒时给出用途说明与「去设置」", async () => {
  picker.getCameraPermissionsAsync.mockResolvedValue({ granted: false } as never);
  picker.requestCameraPermissionsAsync.mockResolvedValue({ granted: false } as never);
  const openSettings = jest.spyOn(Linking, "openSettings").mockResolvedValue(undefined as never);
  const screen = await renderScreen();

  await fireEvent.press(screen.getByLabelText("相机采集"));

  await waitFor(() => expect(screen.getByText("无法使用相机")).toBeTruthy());
  expect(screen.getByText(/系统不会再重复弹出授权提示/)).toBeTruthy();
  expect(picker.launchCameraAsync).not.toHaveBeenCalled();

  await fireEvent.press(screen.getByLabelText("去设置"));
  expect(openSettings).toHaveBeenCalledTimes(1);
});

test("相册权限被拒时给出说明且不打开选择器", async () => {
  picker.getMediaLibraryPermissionsAsync.mockResolvedValue({ granted: false } as never);
  picker.requestMediaLibraryPermissionsAsync.mockResolvedValue({ granted: false } as never);
  const screen = await renderScreen();

  await fireEvent.press(screen.getByLabelText("相册采集"));

  await waitFor(() => expect(screen.getByText("无法访问相册")).toBeTruthy());
  expect(picker.launchImageLibraryAsync).not.toHaveBeenCalled();
});

test("文本采集从剪贴板填入并携带幂等键提交", async () => {
  let form: FormData | null = null;
  globalThis.fetch = jest.fn(async (_url: string, init: RequestInit) => {
    form = init.body as FormData;
    return { ok: true, status: 201, json: async () => ({ id: 21 }) };
  }) as unknown as typeof fetch;
  const screen = await renderScreen();

  await fireEvent.press(screen.getByLabelText("文本采集"));
  await fireEvent.press(await screen.findByLabelText("从剪贴板填入"));
  await waitFor(() => expect(screen.getByDisplayValue("剪贴板里的文字")).toBeTruthy());
  await fireEvent.press(screen.getByLabelText("提交采集"));

  await waitFor(() => expect(screen.getByText("已提交 1 条")).toBeTruthy());
  expect(form!.get("text")).toBe("剪贴板里的文字");
  expect(form!.get("capture_key")).toBe("batch-uuid:1");
  expect(mockRequest).toHaveBeenCalledWith("/api/sources/21/process", { method: "POST" }, "token");
});

test("相册每张一条部分失败时汇总并只提示失败项", async () => {
  picker.getMediaLibraryPermissionsAsync.mockResolvedValue({ granted: true } as never);
  picker.launchImageLibraryAsync.mockResolvedValue({
    canceled: false,
    assets: [asset("file://1.heic"), asset("file://2.heic"), asset("file://3.heic")],
  } as never);
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

  await fireEvent.press(screen.getByLabelText("相册采集"));
  await fireEvent.press(await screen.findByLabelText(/每张一条/));
  await waitFor(() => expect(screen.getByText(/这 3 张将分别作为 3 条材料提交/)).toBeTruthy());
  await fireEvent.press(screen.getByLabelText("提交采集"));

  await waitFor(() => expect(screen.getByText("已提交 2 条，1 条未成功")).toBeTruthy());
  expect(keys).toEqual(["batch-uuid:1", "batch-uuid:2", "batch-uuid:3"]);
  expect(screen.getByText("仅支持 png、jpg、webp 图片")).toBeTruthy();
  expect(screen.getByLabelText("重试这一条")).toBeTruthy();
});
