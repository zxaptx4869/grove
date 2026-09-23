/** 上传前图片预处理：长边 2048、quality 0.8，统一输出 jpg。 */

import { ImageManipulator, SaveFormat } from "expo-image-manipulator";

import type { UploadFile } from "@/src/capture/batch";

export const MAX_IMAGE_EDGE = 2048;
export const IMAGE_QUALITY = 0.8;

export type PickedImage = UploadFile & { width: number; height: number };

/** 系统选择器给出的资源（宽高可能为 0，表示系统没有提供尺寸）。 */
export type PickedAsset = { uri: string; width: number; height: number };

/**
 * 压缩并转码为 jpg：长边超过上限时按朝向缩到 2048（只传长边，避免把竖图放大），
 * 否则只做 jpg 转码。转码同时解决 iOS 默认 HEIC 与单张 10MB 上限。
 */
export async function prepareImage(
  asset: PickedAsset,
  options: { index?: number; now?: number } = {},
): Promise<PickedImage> {
  const index = options.index ?? 1;
  const now = options.now ?? Date.now();
  const context = ImageManipulator.manipulate(asset.uri);
  const longest = Math.max(asset.width, asset.height);
  if (longest > MAX_IMAGE_EDGE) {
    if (asset.width >= asset.height) {
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
  };
}

export async function prepareImages(assets: PickedAsset[], now = Date.now()): Promise<PickedImage[]> {
  const prepared: PickedImage[] = [];
  for (const [position, asset] of assets.entries()) {
    prepared.push(await prepareImage(asset, { index: position + 1, now }));
  }
  return prepared;
}
