/**
 * 来源库局部图标：沿用 AgentIcon / CaptureIcon 的线性风格。
 *
 * 与采集模块共用的图形直接委托给 `CaptureIcon`，避免同一套线条在仓库里抄两遍；
 * 这里只补来源库新增的图形，不改动共享图标集。
 */

import Svg, { Path } from "react-native-svg";

import { CaptureIcon, type CaptureIconName } from "@/src/capture/components/CaptureIcon";

export type SourceIconName =
  | "image"
  | "images"
  | "text"
  | "clock"
  | "check"
  | "alert"
  | "info"
  | "folder"
  | "move"
  | "trash"
  | "zoom"
  | "sprout"
  | "cloudOff"
  | "refresh"
  | "lock"
  | "close"
  | "back";

type DelegatedIconName = "images" | "text" | "check" | "alert" | "info" | "trash" | "cloudOff" | "refresh" | "lock" | "back";

const DELEGATED: Partial<Record<SourceIconName, DelegatedIconName>> = {
  images: "images",
  text: "text",
  check: "check",
  alert: "alert",
  info: "info",
  trash: "trash",
  cloudOff: "cloudOff",
  refresh: "refresh",
  lock: "lock",
  back: "back",
};

const PATHS: Partial<Record<SourceIconName, string[]>> = {
  image: ["M4 6h16v12H4z", "M8.5 11.5a1.3 1.3 0 1 0 0-2.6 1.3 1.3 0 0 0 0 2.6z", "m5 16 4-3.8 3 2.8 2.6-2.3L19 16"],
  clock: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 7.5V12l3 2"],
  folder: ["M3 5h6l2 2h10v12H3z"],
  move: ["M3.5 6.5h5l1.7 1.8h10.3v10.2H3.5z", "M13 12h5", "M16.3 10.1 18.2 12l-1.9 1.9"],
  zoom: ["M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z", "m20.5 20.5-4.2-4.2", "M11 8.6v4.8M8.6 11h4.8"],
  sprout: ["M12 21v-7.5", "M12 13.5C12 10.4 9.6 8 6.5 8h-1c0 3.1 2.4 5.5 5.5 5.5z", "M12 13.5c0-3.4 2.6-6.2 6-6.2h.7c0 3.4-2.6 6.2-6 6.2z"],
  close: ["M18 6 6 18", "M6 6l12 12"],
};

export function SourceIcon({
  name,
  size = 20,
  color,
  strokeWidth = 1.9,
}: {
  name: SourceIconName;
  size?: number;
  color: string;
  strokeWidth?: number;
}) {
  const delegated = DELEGATED[name];
  if (delegated) {
    return (
      <CaptureIcon
        name={delegated as CaptureIconName}
        size={size}
        color={color}
        strokeWidth={strokeWidth}
      />
    );
  }
  const paths = PATHS[name] ?? PATHS.info ?? [];
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      {paths.map((d) => (
        <Path
          key={d}
          d={d}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
    </Svg>
  );
}
