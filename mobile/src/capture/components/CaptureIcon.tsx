/** 采集栏目局部图标：沿用 AgentIcon 的线性风格，不改动共享图标集。 */

import Svg, { Path } from "react-native-svg";

export type CaptureIconName =
  | "camera"
  | "images"
  | "text"
  | "trash"
  | "refresh"
  | "settings"
  | "cloudOff"
  | "info"
  | "alert"
  | "check"
  | "clipboard";

const PATHS: Record<CaptureIconName, string[]> = {
  camera: [
    "M4 8h3l1.5-2h7L17 8h3v11H4z",
    "M12 16.5a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4z",
  ],
  images: [
    "M4 6h12v12H4z",
    "m6.5 15 3-3.5 2.5 2.5 2-2 3.5 3.5",
    "M17.5 9.5 20 7v12.5",
  ],
  text: ["M6 5h12M12 5v14M9 19h6"],
  trash: ["M5 7h14", "M9 7V5h6v2", "M7 7l1 13h8l1-13", "M11 11v6M13 11v6"],
  refresh: ["M20 12a8 8 0 1 1-2.3-5.7L20 8", "M20 4v4h-4"],
  settings: [
    "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z",
    "M19 12c0-.6-.1-1.1-.2-1.6l2-1.4-2-3.4-2.3 1a7.4 7.4 0 0 0-2.8-1.6L13.3 2h-3.9l-.4 2.4A7.4 7.4 0 0 0 6.2 6l-2.3-1-2 3.4 2 1.4A8.2 8.2 0 0 0 3.7 12",
  ],
  cloudOff: ["M6 6l12 12", "M8 8.5A5 5 0 0 1 17 8a4 4 0 0 1-1 7.9H9a4 4 0 0 1-1-7.4"],
  info: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 11v5M12 8h.01"],
  alert: ["M12 3.5 2.5 20h19z", "M12 10v4M12 17h.01"],
  check: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "m8 12 2.7 2.7L16 9.5"],
  clipboard: [
    "M9 4h6v3H9z",
    "M8 5.5H6.5v15h11v-15H16",
    "M9.5 12h5M9.5 15.5h3",
  ],
};

export function CaptureIcon({
  name,
  size = 20,
  color,
  strokeWidth = 1.9,
}: {
  name: CaptureIconName;
  size?: number;
  color: string;
  strokeWidth?: number;
}) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      {PATHS[name].map((d) => (
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
