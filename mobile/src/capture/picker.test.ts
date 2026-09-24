/** 相册选择器选项：Android 走旧式选择器（真机反馈系统照片选择器会闪蓝色进度卡），iOS 保持选择器侧上限。 */

import * as ImagePicker from "expo-image-picker";
import { Platform } from "react-native";

import { pickImages } from "@/src/capture/picker";

jest.mock("expo-image-picker", () => ({ launchImageLibraryAsync: jest.fn() }));

const picker = ImagePicker as jest.Mocked<typeof ImagePicker>;

function withPlatform<T>(os: string, run: () => T): T {
  const original = Platform.OS;
  Object.defineProperty(Platform, "OS", { value: os, configurable: true });
  try {
    return run();
  } finally {
    Object.defineProperty(Platform, "OS", { value: original, configurable: true });
  }
}

test("Android 走旧式选择器并把张数上限交给客户端", async () => {
  picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: [] } as never);

  await withPlatform("android", () => pickImages());

  expect(picker.launchImageLibraryAsync).toHaveBeenCalledWith(
    expect.objectContaining({ legacy: true, selectionLimit: 0, allowsMultipleSelection: true }),
  );
});

test("iOS 仍由选择器限制 5 张", async () => {
  picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: [] } as never);

  await withPlatform("ios", () => pickImages());

  expect(picker.launchImageLibraryAsync).toHaveBeenCalledWith(
    expect.objectContaining({ legacy: false, selectionLimit: 5 }),
  );
});
