/** 系统相机、相册与权限：只调用系统能力，不自建取景或图库界面。 */

import * as ImagePicker from "expo-image-picker";
import { Linking, Platform } from "react-native";

import { MAX_SELECTION } from "@/src/capture/batch";
import type { PickedAsset } from "@/src/capture/image";

export type PermissionKind = "camera" | "album";

/** 只取压缩与上传需要的字段：文件名与 MIME 仅作占位，压缩后会被 jpg 覆盖。 */
function toAsset(asset: ImagePicker.ImagePickerAsset): PickedAsset {
  return {
    uri: asset.uri,
    width: asset.width,
    height: asset.height,
    name: asset.fileName,
    type: asset.mimeType,
  };
}

async function currentPermission(kind: PermissionKind) {
  return kind === "camera"
    ? ImagePicker.getCameraPermissionsAsync()
    : ImagePicker.getMediaLibraryPermissionsAsync();
}

async function requestPermission(kind: PermissionKind) {
  return kind === "camera"
    ? ImagePicker.requestCameraPermissionsAsync()
    : ImagePicker.requestMediaLibraryPermissionsAsync();
}

/** 已有授权直接放行，否则申请一次；被拒后交给界面说明并提供「去设置」。 */
export async function ensurePermission(kind: PermissionKind): Promise<boolean> {
  const current = await currentPermission(kind);
  if (current.granted) return true;
  const requested = await requestPermission(kind);
  return requested.granted;
}

export function openAppSettings(): Promise<void> {
  return Linking.openSettings();
}

/** 系统相机拍 1 张；取消返回 null。 */
export async function capturePhoto(): Promise<PickedAsset | null> {
  const result = await ImagePicker.launchCameraAsync({
    mediaTypes: ["images"],
    allowsMultipleSelection: false,
    quality: 1,
  });
  if (result.canceled) return null;
  const asset = result.assets[0];
  return asset ? toAsset(asset) : null;
}

/**
 * 系统相册多选，最多 5 张。
 *
 * Android 走相册 App 的旧式选择器（`legacy`，即 `ACTION_GET_CONTENT`）：系统照片
 * 选择器（隐私「安全访问」模式）在准备选中的图片时会自己弹一张蓝色进度卡，退场
 * 瞬间闪在采集页上（真机验收反馈），而系统相册入口与其它 App 一致、没有这张卡。
 * 旧式选择器不接受选择器侧张数上限，因此 Android 不下发上限，改由调用方校验并把
 * 超出结果明确提示给用户（MUST NOT 静默丢图）。
 */
export async function pickImages(limit = MAX_SELECTION): Promise<PickedAsset[]> {
  const useLegacyPicker = Platform.OS === "android";
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    allowsMultipleSelection: true,
    selectionLimit: useLegacyPicker ? 0 : limit,
    quality: 1,
    legacy: useLegacyPicker,
  });
  if (result.canceled) return [];
  return result.assets.map(toAsset);
}
