/** 系统相机、相册与权限：只调用系统能力，不自建取景或图库界面。 */

import * as ImagePicker from "expo-image-picker";
import { Linking } from "react-native";

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
 * 系统相册多选，最多 5 张：数量上限交给系统选择器（`selectionLimit`），
 * 不在客户端静默截断；若系统仍返回超量资源，交给提交环节报出「一次最多上传 5 张图片」。
 */
export async function pickImages(limit = MAX_SELECTION): Promise<PickedAsset[]> {
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    allowsMultipleSelection: true,
    selectionLimit: limit,
    quality: 1,
  });
  if (result.canceled) return [];
  return result.assets.map(toAsset);
}
