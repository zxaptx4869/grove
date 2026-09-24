/** 提交时的图片预处理：长边 2048、quality 0.8，统一输出 jpg；进度由提交覆盖层呈现。 */

import { ImageManipulator, SaveFormat } from "expo-image-manipulator";

import type { UploadFile } from "@/src/capture/batch";

export const MAX_IMAGE_EDGE = 2048;
export const IMAGE_QUALITY = 0.8;

/** 表单里的图片：uri 在压缩前指向原图，压缩后指向本地 jpg 副本。 */
export type PickedImage = UploadFile & { width: number; height: number };

/** 压缩入参：uri 必有；宽高缺失或为 0 表示系统没给尺寸，此时只转码不缩放。 */
export type ImageSource = {
  uri: string;
  width?: number | null;
  height?: number | null;
};

/** 系统选择器给出的资源。 */
export type PickedAsset = ImageSource & { name?: string | null; type?: string | null };

/**
 * 把选择器给的资源直接包成草稿图片：表单缩略图沿用原图 uri，
 * 压缩推迟到提交覆盖层内做，避免进入采集页前闪一层准备中提示。
 */
export function draftImages(assets: PickedAsset[]): PickedImage[] {
  return assets.map((asset, position) => ({
    uri: asset.uri,
    name: asset.name?.trim() || `grove-original-${position + 1}.jpg`,
    type: asset.type?.trim() || "image/jpeg",
    // 0 表示系统没给尺寸：压缩时只转码、不缩放
    width: asset.width ?? 0,
    height: asset.height ?? 0,
    prepared: false,
  }));
}

/**
 * 压缩并转码为 jpg：长边超过上限时按朝向缩到 2048（只传长边，避免把竖图放大），
 * 否则只做 jpg 转码。转码同时解决 iOS 默认 HEIC 与单张 10MB 上限。
 * 已在提交时执行，进度由提交覆盖层呈现。
 */
export async function prepareImage(
  asset: ImageSource,
  options: { index?: number; now?: number } = {},
): Promise<PickedImage> {
  const index = options.index ?? 1;
  const now = options.now ?? Date.now();
  const width = asset.width ?? 0;
  const height = asset.height ?? 0;
  const context = ImageManipulator.manipulate(asset.uri);
  if (Math.max(width, height) > MAX_IMAGE_EDGE) {
    if (width >= height) {
      context.resize({ width: MAX_IMAGE_EDGE });
    } else {
      context.resize({ height: MAX_IMAGE_EDGE });
    }
  }
  const image = await context.renderAsync();
  const saved = await image.saveAsync({ compress: IMAGE_QUALITY, format: SaveFormat.JPEG });
  return {
    uri: saved.uri,
    name: `grove-${now}-${index}.jpg`,
    type: "image/jpeg",
    width: saved.width,
    height: saved.height,
    prepared: true,
  };
}
